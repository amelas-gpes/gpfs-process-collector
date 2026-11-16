"""The pause that ends a turn in reviewed voice is a bounded setting (live-voice-reviewed-1)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_server import server


class ReviewedVoicePauseTests(unittest.TestCase):
    def config(self, **settings):
        return server.OpenAIClient({'OPENAI_API_KEY': 'synthetic-only', **settings}).public_config()

    def test_reviewed_mode_reports_the_default_pause(self):
        self.assertEqual(self.config(VOICE_MODE='reviewed')['agent_team']['turn_pause_ms'], 1800)

    def test_a_configured_pause_is_reported_to_the_page(self):
        self.assertEqual(self.config(VOICE_MODE='reviewed', VOICE_PAUSE_MS='2500')['agent_team']['turn_pause_ms'], 2500)
        self.assertEqual(self.config(VOICE_MODE='reviewed', VOICE_PAUSE_MS=' 3000 ')['agent_team']['turn_pause_ms'], 3000)

    def test_the_pause_is_kept_within_the_supported_range(self):
        self.assertEqual(self.config(VOICE_MODE='reviewed', VOICE_PAUSE_MS='200')['agent_team']['turn_pause_ms'], 1000)
        self.assertEqual(self.config(VOICE_MODE='reviewed', VOICE_PAUSE_MS='60000')['agent_team']['turn_pause_ms'], 5000)
        self.assertEqual(self.config(VOICE_MODE='reviewed', VOICE_PAUSE_MS='-5')['agent_team']['turn_pause_ms'], 1000)

    def test_an_unusable_value_falls_back_to_the_default_instead_of_stopping_the_server(self):
        for value in ('', 'soon', '2.5s', None):
            with self.subTest(value=value):
                self.assertEqual(self.config(VOICE_MODE='reviewed', VOICE_PAUSE_MS=value)['agent_team']['turn_pause_ms'], 1800)

    def test_live_mode_does_not_report_a_setting_it_does_not_use(self):
        self.assertNotIn('turn_pause_ms', self.config(VOICE_PAUSE_MS='2500')['agent_team'])
        self.assertNotIn('turn_pause_ms', self.config(VOICE_MODE='live')['agent_team'])

    def test_the_setting_is_read_from_the_local_settings_file(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, '.env.local').write_text('VOICE_MODE=reviewed\nVOICE_PAUSE_MS=2200\n', encoding='utf-8')
            clean = {key: value for key, value in os.environ.items() if key not in ('VOICE_MODE', 'VOICE_PAUSE_MS')}
            with patch.object(server, 'APP_DIR', Path(folder)), patch.dict(os.environ, clean, clear=True):
                settings = server.load_settings()
        self.assertEqual(settings.get('VOICE_PAUSE_MS'), '2200')
        self.assertEqual(server.OpenAIClient({'OPENAI_API_KEY': 'synthetic-only', **settings}).public_config()['agent_team']['turn_pause_ms'], 2200)


if __name__ == '__main__':
    unittest.main()
