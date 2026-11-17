"""Synthetic pixels and fake OCR only: no personal screenshots, GUI, API, or network."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import desktop
import screenshot_privacy as privacy


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for key in ('SCREENSHOT_PRIVACY', 'SCREENSHOT_MASKS', 'SCREENSHOT_KEEP'):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize('key,value', [
    ('SCREENSHOT_PRIVACY', 'unknown'), ('SCREENSHOT_KEEP', '0'),
    ('SCREENSHOT_MASKS', '[[0,0,1,1]]'), ('SCREENSHOT_MASKS', '{}'),
    ('SCREENSHOT_MASKS', '[[0,0,2,1]]'), ('SCREENSHOT_MASKS', '[[NaN,0,1,1]]'),
    ('SCREENSHOT_MASKS', '[[false,0,1,1]]'), ('SCREENSHOT_MASKS', '[[0,0,-1,1]]')])
def test_bad_configuration_blocks_capture(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(privacy.PrivacyError):
        privacy.PrivacyConfig.from_env()


def test_off_never_loads_image_or_runs_ocr(monkeypatch, tmp_path):
    monkeypatch.setattr(privacy, 'ocr_boxes', lambda _: pytest.fail('OCR called'))
    path = tmp_path / 'not-an-image'
    path.write_bytes(b'unchanged')
    assert privacy.protect(path, privacy.PrivacyConfig()) == 0
    assert path.read_bytes() == b'unchanged'


def test_masks_preserve_dimensions_and_unmasked_pixels(monkeypatch, tmp_path):
    monkeypatch.setattr(privacy, 'ocr_boxes', lambda _: pytest.fail('OCR called'))
    path = tmp_path / 'screen.jpg'
    Image.new('RGB', (400, 200), 'white').save(path)
    privacy.protect(path, privacy.PrivacyConfig('masks', ((.1, .2, .3, .2),)))
    with Image.open(path) as image:
        assert image.size == (400, 200)
        assert max(image.getpixel((70, 55))) < 10
        assert min(image.getpixel((350, 170))) > 245


HEADER = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'


def tsv(lines):
    rows = [HEADER]
    for line_number, words in enumerate(lines, 1):
        for i, word in enumerate(words):
            rows.append(f'5\t1\t1\t1\t{line_number}\t{i+1}\t{i*80}\t{line_number*30}\t70\t20\t90\t{word}\n')
    return ''.join(rows)


@pytest.mark.parametrize('words', [
    ['alice@example.org'], ['alice', '@', 'example.org'], ['123-45-6789'],
    ['(415)', '555-0123'], ['4111', '1111', '1111', '1111'],
    ['api_key:', 'not-a-real-secret'], ['password', '=', 'test-only'],
    ['sk-fakeexamplecredential12345'], ['Bearer', 'test-only-token']])
def test_ocr_redacts_sensitive_spans_without_logging_text(monkeypatch, words):
    monkeypatch.setattr(privacy.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=tsv([words])))
    boxes = privacy.ocr_boxes(Path('synthetic.jpg'))
    assert len(boxes) == len(words)


def test_ocr_does_not_mask_ordinary_task_text(monkeypatch):
    monkeypatch.setattr(privacy.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=tsv([['Open', 'Notes', '42']])) )
    assert privacy.ocr_boxes(Path('synthetic.jpg')) == []


@pytest.mark.parametrize('error', [FileNotFoundError(), subprocess.TimeoutExpired('ocr', 15),
                                  subprocess.CalledProcessError(1, 'ocr', stderr='private text')])
def test_ocr_errors_are_closed_and_do_not_disclose_output(monkeypatch, error):
    def fail(*a, **k):
        raise error
    monkeypatch.setattr(privacy.subprocess, 'run', fail)
    with pytest.raises(privacy.PrivacyError) as caught:
        privacy.ocr_boxes(Path('synthetic.jpg'))
    assert 'private' not in str(caught.value)


@pytest.mark.parametrize('failure', ['capture', 'redaction', 'resize', None])
def test_capture_publishes_only_processed_images_and_cleans_originals(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(desktop, 'SCREENSHOT_DIR', tmp_path)
    monkeypatch.setenv('SCREENSHOT_PRIVACY', 'masks')
    monkeypatch.setenv('SCREENSHOT_MASKS', '[[0,0,0.5,1]]')
    def run(command, **kwargs):
        path = Path(command[-1])
        if command[0] == 'screencapture':
            Image.new('RGB', (400, 200), 'white').save(path)
            assert path.parent.stat().st_mode & 0o777 == 0o700
            if failure == 'capture':
                raise subprocess.CalledProcessError(1, command)
        elif failure == 'resize':
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace()
    monkeypatch.setattr(desktop.subprocess, 'run', run)
    if failure == 'redaction':
        def fail(*a):
            raise privacy.PrivacyError('blocked')
        monkeypatch.setattr(privacy, 'protect', fail)
    if failure:
        with pytest.raises((subprocess.CalledProcessError, privacy.PrivacyError)):
            desktop.take_screenshot()
        assert not list(tmp_path.iterdir())
    else:
        path = desktop.take_screenshot()
        assert list(tmp_path.iterdir()) == [path]
        assert path.stat().st_mode & 0o777 == 0o600
        with Image.open(path) as image:
            assert max(image.getpixel((50, 50))) < 10
            assert min(image.getpixel((350, 50))) > 245


def test_retention_ignores_other_artifacts_and_symlinks(tmp_path):
    paths = [tmp_path / f'screen-{i}.jpg' for i in range(4)]
    for p in paths:
        p.write_bytes(b'image')
    graph = tmp_path / 'latest.png'
    graph.write_bytes(b'graph')
    link = tmp_path / 'screen-link.jpg'
    link.symlink_to(graph)
    privacy.prune(tmp_path, 2, paths[-1])
    assert not paths[0].exists() and not paths[1].exists()
    assert paths[2].exists() and paths[3].exists()
    assert graph.exists() and link.is_symlink()


@pytest.mark.parametrize('output', ['', 'broken output', HEADER + '5\t1\n'])
def test_malformed_ocr_response_blocks_capture(monkeypatch, output):
    monkeypatch.setattr(privacy.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=output))
    with pytest.raises(privacy.PrivacyError):
        privacy.ocr_boxes(Path('synthetic.jpg'))


def test_ocr_masking_uses_detected_word_coordinates(monkeypatch, tmp_path):
    path = tmp_path / 'synthetic.jpg'
    Image.new('RGB', (400, 200), 'white').save(path)
    monkeypatch.setattr(privacy.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=tsv([['alice@example.org']])))
    assert privacy.protect(path, privacy.PrivacyConfig('ocr')) == 1
    with Image.open(path) as image:
        assert max(image.getpixel((30, 40))) < 10
        assert min(image.getpixel((300, 100))) > 245


def test_operator_reports_blocked_capture_without_actions(monkeypatch, tmp_path):
    import asyncio
    monkeypatch.setenv('TELEMETRY_MODE', 'screenshot')
    monkeypatch.setenv('TELEMETRY_ROOTS', '[]')
    monkeypatch.setenv('TELEMETRY_RUN_DIR', str(tmp_path))
    def blocked():
        raise privacy.PrivacyError('Local screenshot OCR unavailable or failed; capture blocked.')
    monkeypatch.setattr(desktop, 'take_screenshot', blocked)
    async def fake_run(*args, **kwargs):
        desktop.take_screenshot()
        pytest.fail('must not continue')
    monkeypatch.setattr(desktop.Runner, 'run', fake_run)
    result = asyncio.run(desktop.run_operator('Open Notes'))
    assert result.startswith('stopped:') and 'capture blocked' in result
    assert desktop.ACTIVE_RUN.get() is None


def test_invalid_configuration_does_not_start_operator_or_create_run(monkeypatch, tmp_path):
    import asyncio
    monkeypatch.setenv('SCREENSHOT_PRIVACY', 'invalid')
    monkeypatch.setenv('TELEMETRY_RUN_DIR', str(tmp_path))
    result = asyncio.run(desktop.run_operator('Open Notes'))
    assert result.startswith('stopped: Invalid screenshot privacy configuration')
    assert desktop.ACTIVE_RUN.get() is None
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('mode', ['masks', 'ocr'])
def test_fabricated_screenshot_end_to_end(monkeypatch, tmp_path, mode):
    """Readable synthetic desktop through capture -> filter -> resize -> model encoding."""
    import base64
    import io
    from PIL import ImageDraw, ImageChops, ImageStat

    source = Image.new('RGB', (1600, 900), '#eef2f6')
    draw = ImageDraw.Draw(source)
    draw.rectangle((0, 0, 1600, 80), fill='#21364b')
    draw.text((45, 22), 'SYNTHETIC DESKTOP / PRIVACY TEST', fill='white', font_size=32)
    draw.rounded_rectangle((65, 130, 1535, 800), radius=20, fill='white')
    draw.text((105, 165), 'Project workspace', fill='#21364b', font_size=40)
    draw.text((105, 245), 'Sensitive field (fabricated):', fill='#536477', font_size=28)
    secret = 'alice@example.org'
    bbox = draw.textbbox((105, 300), secret, font_size=40)
    draw.text((105, 300), secret, fill='#b12d36', font_size=40)
    draw.text((105, 425), 'Task: Open the project folder.', fill='#21364b', font_size=36)
    draw.text((105, 500), 'Status: Ready to continue.', fill='#21364b', font_size=32)
    draw.text((105, 700), 'All content in this image is fabricated.', fill='#536477', font_size=27)
    before = tmp_path / 'before.jpg'
    source.save(before, quality=95)
    capture_dir = tmp_path / 'captures'
    monkeypatch.setattr(desktop, 'SCREENSHOT_DIR', capture_dir)
    monkeypatch.setenv('SCREENSHOT_PRIVACY', mode)
    x, y, right, bottom = bbox
    monkeypatch.setenv('SCREENSHOT_MASKS', '[]' if mode == 'ocr' else
                       __import__('json').dumps([[x/1600, y/900, (right-x)/1600, (bottom-y)/900]]))
    seen = []
    def fake_run(command, **kwargs):
        seen.append(command[0])
        if command[0] == 'screencapture':
            Path(command[-1]).write_bytes(before.read_bytes())
        elif command[0] == 'tesseract':
            # OCR engine is mocked; detection patterns, coordinates, and masking are real.
            row = f'5\t1\t1\t1\t1\t1\t{x}\t{y}\t{right-x}\t{bottom-y}\t95\t{secret}\n'
            return SimpleNamespace(stdout=HEADER + row)
        elif command[0] == 'sips':
            path = Path(command[-1])
            with Image.open(path) as image:
                resized = image.resize((1280, 720))
            resized.save(path, quality=95)
        else:
            pytest.fail(f'unexpected command {command[0]}')
        return SimpleNamespace()
    monkeypatch.setattr(desktop.subprocess, 'run', fake_run)
    result = desktop.take_screenshot()
    encoded = desktop.image_url(result)
    with Image.open(io.BytesIO(base64.b64decode(encoded.split(',', 1)[1]))) as after:
        assert after.size == (1280, 720)
        # Entire detected word rectangle must be black, including its original glyphs.
        sensitive = after.crop((int(x*.8), int(y*.8), int(right*.8), int(bottom*.8)))
        assert max(ImageStat.Stat(sensitive).mean) < 5
        with Image.open(before) as original:
            reference = original.resize((1280, 720))
        ordinary = (70, 330, 1100, 470)
        diff = ImageChops.difference(reference.crop(ordinary), after.crop(ordinary))
        assert max(ImageStat.Stat(diff).mean) < 3
        after.save(tmp_path / 'after.png')
    assert seen == (['screencapture', 'tesseract', 'sips'] if mode == 'ocr' else ['screencapture', 'sips'])
    assert not list(capture_dir.glob('.capture-*'))


def test_real_tesseract_on_fabricated_screenshot(tmp_path):
    """Optional integration test: genuine local OCR, with no mocked engine or boxes."""
    import shutil
    import time
    from PIL import ImageDraw, ImageStat, ImageChops
    if shutil.which('tesseract') is None:
        pytest.skip('Install Tesseract to run the real local OCR integration test')
    source = Image.new('RGB', (1600, 900), '#eef2f6')
    draw = ImageDraw.Draw(source)
    draw.rectangle((0, 0, 1600, 80), fill='#21364b')
    draw.text((45, 22), 'SYNTHETIC DESKTOP / REAL OCR TEST', fill='white', font_size=32)
    draw.rounded_rectangle((65, 130, 1535, 800), radius=20, fill='white')
    draw.text((105, 165), 'Project workspace', fill='#21364b', font_size=40)
    draw.text((105, 235), 'Fabricated private information:', fill='#536477', font_size=28)
    secrets = [('alice@example.org', 295), ('123-45-6789', 375)]
    bounds = []
    for text, y in secrets:
        bounds.append(draw.textbbox((105, y), text, font_size=40))
        draw.text((105, y), text, fill='#b12d36', font_size=40)
    draw.text((105, 510), 'Task: Open the project folder.', fill='#21364b', font_size=36)
    draw.text((105, 585), 'Status: Ready to continue.', fill='#21364b', font_size=32)
    draw.text((105, 715), 'All content in this image is fabricated.', fill='#536477', font_size=27)
    before = tmp_path / 'before.jpg'
    after = tmp_path / 'after.jpg'
    source.save(before, quality=95)
    after.write_bytes(before.read_bytes())
    started = time.monotonic()
    count = privacy.protect(after, privacy.PrivacyConfig('ocr'))
    elapsed = time.monotonic() - started
    assert count >= len(secrets)
    with Image.open(after) as censored, Image.open(before) as original:
        assert censored.size == original.size
        for box in bounds:
            # Exclude outer JPEG boundary; all text in each expected region is obscured.
            x, y, right, bottom = box
            region = censored.crop((x+2, y+2, right-2, bottom-2))
            assert max(ImageStat.Stat(region).mean) < 5
        ordinary = (90, 490, 1300, 650)
        diff = ImageChops.difference(original.crop(ordinary), censored.crop(ordinary))
        assert max(ImageStat.Stat(diff).mean) < 3
    print(f'Real Tesseract: {count} redaction regions, {elapsed:.3f}s processing')
