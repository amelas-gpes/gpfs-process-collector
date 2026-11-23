"""Authenticated OpenAI HTTP transport for the local development provider."""
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from functools import cache
from http.client import HTTPSConnection
import io
import socket
import threading
import time
from typing import BinaryIO, Protocol
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class ProviderTransport(Protocol):
    """Open one POST and own its response and cancellation watcher until context exit."""

    def __call__(
        self, path: str, data: bytes, *, key: str, content_type: str, timeout: float,
        check_active: Callable[[], None], should_abort: Callable[[], bool] | None,
    ) -> AbstractContextManager[BinaryIO]: ...


class NoProviderRedirect(HTTPRedirectHandler):
    """An authenticated API request is valid only for its original endpoint."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ProviderResponseReader(io.RawIOBase):
    """Check cancellation between bounded socket reads, underneath HTTP's buffer."""
    def __init__(self, sock, owner, check_active):
        self.sock, self.owner, self.check_active = sock, owner, check_active
        self.previous_timeout = sock.gettimeout()
        sock.settimeout(min(.25, self.previous_timeout) if self.previous_timeout is not None else .25)

    def readable(self):
        return True

    def readinto(self, buffer):
        while True:
            self.check_active()
            try:
                return self.sock.recv_into(buffer)
            except TimeoutError:
                # No bytes were returned by this recv. The HTTP buffer keeps everything
                # from earlier reads, including an unfinished header or body.
                continue

    def close(self):
        if not self.closed:
            try:
                self.sock.settimeout(self.previous_timeout)
            except OSError:
                pass
            finally:
                # HTTPResponse's original file keeps the transport alive after the
                # HTTPConnection hands ownership to its response.
                self.owner.close()
                super().close()


class ProviderTLSHandshake:
    """Use the connection's TLS configuration and check cancellation while the peer negotiates."""
    def __init__(self, context, check_active):
        self.context = context
        self.check_active = check_active

    def wrap_socket(self, sock, **options):
        # HTTPSConnection supplies the origin hostname, including when using a proxy tunnel.
        transport = self.context.wrap_socket(sock, do_handshake_on_connect=False, **options)
        try:
            timeout = transport.gettimeout()
            transport.settimeout(min(.25, timeout) if timeout is not None else .25)
            while True:
                self.check_active()
                try:
                    transport.do_handshake()
                    break
                except TimeoutError:
                    continue
            transport.settimeout(timeout)
            return transport
        except BaseException:
            # wrap_socket transferred the descriptor; the connection still holds the detached socket.
            transport.close()
            raise


class NamesProviderSockets:
    """Names each connection's socket to the request that opened it (request.provider_sockets).

    A request to the AI service that is not streamed sends nothing back until the whole
    answer exists. Its thread waits inside urlopen for the status line, where no code of
    this application runs. The socket named here is what lets OpenAIClient.request end that
    wait when the request is cancelled or its time is up (see _release_on_deadline): until
    it could, a cancelled map kept its worker and a provider slot for up to four minutes.
    """
    def do_open(self, http_class, req, **http_conn_args):
        sockets = getattr(req, "provider_sockets", None)

        def watched(host, **options):
            connection = http_class(host, **options)
            check_active = getattr(req, "check_provider_active", None)
            if check_active is not None:
                if isinstance(connection, HTTPSConnection):
                    connection._context = ProviderTLSHandshake(connection._context, check_active)
                response_type = connection.response_class

                def watched_response(sock, *args, **kwargs):
                    response = response_type(sock, *args, **kwargs)
                    # HTTPResponse has opened its socket file but has not started parsing.
                    # A local shutdown may leave a Windows readiness wait blocked. Check
                    # on the reading thread even when no status line or body bytes arrive.
                    response.fp = io.BufferedReader(ProviderResponseReader(sock, response.fp, check_active))
                    return response

                connection.response_class = watched_response
            if sockets is not None:
                connect = connection.connect

                def connect_and_name():
                    try:
                        connect()
                    finally:
                        if connection.sock is not None:
                            sockets.append(connection.sock)
                connection.connect = connect_and_name
            return connection
        return super().do_open(watched, req, **http_conn_args)


class WatchedHTTPSHandler(NamesProviderSockets, HTTPSHandler):
    pass


@cache
def _opener():
    # urllib discovers the host's proxy settings when it constructs its handlers.
    return build_opener(NoProviderRedirect(), WatchedHTTPSHandler())


def urlopen(request, timeout):
    return _opener().open(request, timeout=timeout)


# The clock of the provider watchdog thread. It is read here once, so that a test which
# replaces time.monotonic to walk a deadline does not hand its prepared values to that thread.
_steady_clock = time.monotonic


@contextmanager
def _release_on_deadline(sockets, seconds, should_abort):
    """End a provider exchange when its time is up or it is cancelled, wherever it waits.

    sockets is the list WatchedHTTPSHandler fills for this request. The watch starts
    before the request is sent: a reply that is not streamed arrives all at once, so a
    watch that began with the response headers (as it used to) saw a cancellation only
    when the provider had finished anyway. A reply trickled past the deadline is ended
    the same way. Shutting the socket makes the blocked read fail; request() already
    reports that as cancelled or as a timeout. With a stand-in urlopen no socket is
    ever named and this only waits to be told the exchange is over.
    """
    done = threading.Event()
    end = _steady_clock() + seconds

    def cancelled():
        try:
            return bool(should_abort and should_abort())
        except Exception:
            return False

    def stop_exchange():
        while not done.is_set():
            remaining = end - _steady_clock()
            if remaining <= 0 or cancelled():
                if not sockets:
                    # Still connecting: the socket is named as soon as it exists.
                    done.wait(.05)
                    continue
                for sock in list(sockets):
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                return
            done.wait(min(.25, remaining) if should_abort else remaining)
    watchdog = threading.Thread(target=stop_exchange, daemon=True, name="provider-read-deadline")
    watchdog.start()
    try:
        yield
    finally:
        done.set()
        watchdog.join(timeout=1)


@contextmanager
def exchange(
    path: str, data: bytes, *, key: str, content_type: str, timeout: float,
    check_active: Callable[[], None], should_abort: Callable[[], bool] | None,
) -> Iterator[BinaryIO]:
    request = Request("https://api.openai.com/v1/" + path, data=data,
                      headers={"Content-Type": content_type}, method="POST")
    request.add_unredirected_header("Authorization", "Bearer " + key)
    request.provider_sockets = []
    request.check_provider_active = check_active
    with _release_on_deadline(request.provider_sockets, timeout, should_abort):
        with urlopen(request, timeout=timeout) as response:
            yield response
