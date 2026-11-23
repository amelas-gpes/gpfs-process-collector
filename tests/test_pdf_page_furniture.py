"""A PDF page of text with rules, boxes and bullets is not a page with unread graphics.

Finding 12 of docs/testing/runs/2026-11-16-process-capture: every page of the uploaded procedures
was sent for visual review and reported as holding unread graphics, although the pages hold
ordinary text. Their exporter puts a whole page (text, table rules, bullets) inside one form
object, and the parser counted the form itself as a graphic.
"""
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('furniture_documents', ROOT / 'documents.py')
documents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(documents)

SAMPLES = ROOT / 'docs' / 'testing' / 'runs' / '2026-11-16-process-capture' / 'uploads' / 'inputs'
PARAGRAPH = ('The treasury analyst compares each approved payment with its release instruction, '
             'records the approver and the value date in the payment register, and returns any '
             'difference to the requester before the batch is released to the bank.')
# A filled disc about four points across, as an exporter draws a list bullet.
BULLET = (b' 52 100 m 52 101.1 51.1 102 50 102 c 48.9 102 48 101.1 48 100 c'
          b' 48 98.9 48.9 98 50 98 c 51.1 98 52 98.9 52 100 c f')
# A table: a shaded header bar, a border and two ruled lines, all horizontal or vertical.
TABLE = (b' 0.9 g 40 300 500 20 re f 0 g 40 200 500 120 re S'
         b' 40 260 m 540 260 l S 290 200 m 290 320 l S')
# A box with rounded corners around a note.
CALLOUT = (b' 60 500 m 520 500 l 525.5 500 530 504.5 530 510 c 530 560 l 530 565.5 525.5 570 520 570 c'
           b' 60 570 l 54.5 570 50 565.5 50 560 c 50 510 l 50 504.5 54.5 500 60 500 c h S')
ARROW = b' 100 400 m 300 400 l S 300 400 m 292 404 l 292 396 l h f'
# Two strokes each: one stroke alone on a page has always been read as an underline.
SLANTED = b' 100 400 m 300 520 l S 100 380 m 300 500 l S'
LARGE_CURVE = b' 100 400 m 150 480 250 480 300 400 c S 100 300 m 150 380 250 380 300 300 c S'


def text_commands(paragraphs=2):
    lines, y = [], 740
    for _ in range(paragraphs):
        for start in range(0, len(PARAGRAPH), 80):
            lines.append(f'BT /F1 10 Tf 56 {y} Td ({PARAGRAPH[start:start + 80]}) Tj ET')
            y -= 14
    return ' '.join(lines).encode()


def pdf_bytes(pages):
    """One page per entry: a dict with 'text' (bytes of text operators, may be empty), 'drawn'
    (bytes of drawing operators), 'form' (put everything in one form object) and 'image'
    (None, or the size in points an image is drawn at)."""
    PdfWriter = documents.pdf_reader().PdfWriter
    from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject
    writer = PdfWriter()
    for spec in pages:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        resources = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        command = spec.get('text', b'') + spec.get('drawn', b'')
        if spec.get('image'):
            image = DecodedStreamObject()
            image.set_data(b'\x00\x00\x00\xff\xff\xff' * 8)
            image.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                          NameObject('/Width'): NumberObject(4), NameObject('/Height'): NumberObject(4),
                          NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
            resources[NameObject('/XObject')] = DictionaryObject({NameObject('/Im1'): writer._add_object(image)})
            width, height = spec['image']
            command += f' q {width} 0 0 {height} 60 60 cm /Im1 Do Q'.encode()
        if spec.get('form'):
            form = DecodedStreamObject()
            # The exporter scales its own units to the page inside the form.
            form.set_data(b'q 0.5 0 0 0.5 0 0 cm 2 0 0 2 0 0 cm ' + command + b' Q')
            form.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Form'),
                         NameObject('/BBox'): ArrayObject([FloatObject(value) for value in (0, 0, 612, 792)]),
                         NameObject('/Resources'): resources})
            resources = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Fm1'): writer._add_object(form)})})
            command = b'q 1 0 0 1 0 0 cm /Fm1 Do Q'
        page[NameObject('/Resources')] = resources
        contents = DecodedStreamObject()
        contents.set_data(command)
        page[NameObject('/Contents')] = writer._add_object(contents)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@unittest.skipUnless(importlib.util.find_spec('pypdf'), 'Existing PDF runtime required')
class PageFurnitureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = documents.DocumentStore(Path(self.temporary.name) / 'documents')
        self.scope = self.store.create_scope()

    def extract(self, name, data):
        record = self.store.extract(self.scope, self.store.add(self.scope, name, data)['id'])
        self.assertIn(record['status'], ('ready', 'partial'), record.get('error'))
        return record

    def test_text_pages_with_rules_boxes_and_bullets_are_fully_indexed_text(self):
        text = text_commands()
        cases = {'table': TABLE, 'bullets': BULLET * 6, 'rounded box': CALLOUT, 'all of them': TABLE + BULLET * 6 + CALLOUT}
        for name, drawn in cases.items():
            for form in (False, True):
                with self.subTest(furniture=name, form=form):
                    record = self.extract(f'{name}-{form}.pdf', pdf_bytes([{'text': text, 'drawn': drawn, 'form': form}]))
                    self.assertEqual(record['status'], 'ready')
                    self.assertEqual(record['inventory']['vision_pages'], [])
                    self.assertEqual(record['inventory']['mixed_visual_pages'], [])
                    self.assertEqual(record['coverage']['limitations'], [])
                    self.assertEqual((record['coverage']['indexed_units'], record['coverage']['text_indexed_units'],
                                      record['coverage']['visual_pending_units'], record['coverage']['total_units']), (1, 1, 0, 1))
                    chunks = self.store.chunks(self.scope, record['id'])['chunks']
                    self.assertTrue(chunks)
                    self.assertFalse(any(chunk.get('requires_vision') for chunk in chunks),
                                     'A page of text and rules must not be given a visual placeholder')
                    self.assertIn('treasury analyst', ' '.join(chunk['text'] for chunk in chunks))

    def test_a_page_whose_form_holds_only_text_is_plain_text(self):
        record = self.extract('form-text.pdf', pdf_bytes([{'text': text_commands(), 'form': True}]))
        self.assertEqual((record['status'], record['inventory']['vision_pages']), ('ready', []))

    def test_drawings_and_images_on_a_text_page_still_need_a_visual_reading(self):
        text = text_commands()
        cases = {'arrow': {'drawn': ARROW}, 'slanted line': {'drawn': SLANTED}, 'large curve': {'drawn': LARGE_CURVE},
                 'shading': {'drawn': b' /Sh1 sh'}, 'image': {'image': (300, 200)},
                 'arrow beside a table': {'drawn': TABLE + ARROW}}
        for name, spec in cases.items():
            for form in (False, True):
                with self.subTest(drawing=name, form=form):
                    record = self.extract(f'{name}-{form}.pdf', pdf_bytes([{'text': text, 'form': form, **spec}]))
                    self.assertEqual(record['status'], 'partial')
                    self.assertEqual(record['inventory']['mixed_visual_pages'], [1])
                    self.assertEqual(record['coverage']['indexed_units'], 0)
                    self.assertEqual(record['coverage']['text_indexed_units'], 1)
                    chunks = self.store.chunks(self.scope, record['id'])['chunks']
                    self.assertEqual(sum(bool(chunk.get('requires_vision')) for chunk in chunks), 1)
                    # The native text is kept beside the placeholder for the graphic.
                    self.assertIn('treasury analyst', ' '.join(chunk['text'] for chunk in chunks if not chunk.get('requires_vision')))

    def test_an_image_only_control_page_still_triggers_visual_review(self):
        for form in (False, True):
            with self.subTest(form=form):
                record = self.extract(f'scan-{form}.pdf', pdf_bytes([
                    {'text': text_commands(), 'drawn': TABLE, 'form': form}, {'image': (500, 700), 'form': form}]))
                self.assertEqual(record['status'], 'partial')
                self.assertEqual(record['inventory']['vision_pages'], [2])
                self.assertEqual(record['inventory']['mixed_visual_pages'], [])
                self.assertEqual((record['coverage']['indexed_units'], record['coverage']['visual_pending_units']), (1, 1))
                chunks = self.store.chunks(self.scope, record['id'])['chunks']
                self.assertEqual([bool(chunk.get('requires_vision')) for chunk in chunks][-1], True)

    def test_small_marks_set_in_the_text_are_not_graphics(self):
        text = text_commands()
        icon = {'image': (10, 10)}  # an icon the size of a letter
        rule = {'image': (400, 1.5)}  # a rule stored as a stretched image
        for name, spec in (('icon', icon), ('image rule', rule)):
            with self.subTest(mark=name):
                record = self.extract(name + '.pdf', pdf_bytes([{'text': text, **spec}]))
                self.assertEqual((record['status'], record['inventory']['vision_pages']), ('ready', []))

    def test_a_page_with_little_text_keeps_the_cautious_answer(self):
        # A box on a nearly empty page can be the page's content (a diagram of boxes, a chart).
        short = b'BT /F1 12 Tf 20 160 Td (Native process instruction) Tj ET'
        record = self.extract('sparse.pdf', pdf_bytes([{'text': short, 'drawn': b' 20 40 100 50 re S'}]))
        self.assertEqual((record['status'], record['inventory']['mixed_visual_pages']), ('partial', [1]))

    def test_a_drawing_the_check_cannot_follow_is_treated_as_a_drawing(self):
        text = text_commands()
        # Too many operators to judge within the bound: the page keeps the cautious answer.
        with unittest.mock.patch.object(documents, 'PDF_DRAWING_OPERATIONS', 5):
            record = self.extract('bounded.pdf', pdf_bytes([{'text': text, 'drawn': TABLE}]))
        self.assertEqual(record['inventory']['mixed_visual_pages'], [1])
        self.assertTrue(documents._pdf_path_is_drawing([('l', ((0, 0), (100, 60)))]))
        self.assertFalse(documents._pdf_path_is_drawing([('l', ((0, 0), (100, 0))), ('l', ((100, 0), (100, 60)))]))

    def test_the_time_spent_on_the_check_is_not_taken_from_the_text_extraction(self):
        text = text_commands()
        with unittest.mock.patch.object(documents, 'PDF_DRAWING_SECONDS', 0.0):
            record = self.extract('no-time.pdf', pdf_bytes([{'text': text, 'drawn': TABLE}] * 3))
        # Without time for the check every painting page keeps the cautious answer; none fails.
        self.assertEqual(record['status'], 'partial')
        self.assertEqual(record['inventory']['mixed_visual_pages'], [1, 2, 3])

    @unittest.skipUnless((SAMPLES / 'U4 MC-07 Manco Treasury & Payment Release.pdf').is_file(), 'Testing corpus not present')
    def test_the_uploaded_procedures_of_the_november_run_are_text_only(self):
        for name, pages in (('U4 MC-07 Manco Treasury & Payment Release.pdf', 4),
                            ('U10 GP-03 Carry Vesting & Carry Point Reallocation.pdf', 24)):
            with self.subTest(file=name):
                record = self.extract(name, (SAMPLES / name).read_bytes())
                self.assertEqual(record['status'], 'ready')
                self.assertEqual(record['inventory']['pages'], pages)
                self.assertEqual(record['inventory']['vision_pages'], [])
                self.assertEqual(record['chunk_count'], pages)
                self.assertEqual((record['coverage']['indexed_units'], record['coverage']['text_indexed_units'],
                                  record['coverage']['visual_pending_units']), (pages, pages, 0))


if __name__ == '__main__':
    unittest.main()
