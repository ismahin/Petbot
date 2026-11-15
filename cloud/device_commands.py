"""Explicit spoken hardware commands; never infer actions from LLM output."""
import unicodedata


def camera_command(text):
    text = ''.join(c if c.isspace() or unicodedata.category(c)[0] in 'LNM' else ' '
                   for c in unicodedata.normalize('NFC', text.lower()))
    text = ' '.join(text.split())
    for prefix in ('hey deskter ', 'hey dexter ', 'deskter ', 'dexter '):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    if text in {'open camera', 'open the camera', 'turn on the camera',
                'ক্যামেরা খোলো', 'ক্যামেরা খোল', 'ক্যামেরা চালু করো', 'ক্যামেরা চালু কর', 'ওপেন ক্যামেরা'}:
        return 'camera_open'
    if text in {'close camera', 'close the camera', 'turn off the camera',
                'ক্যামেরা বন্ধ করো', 'ক্যামেরা বন্ধ কর', 'ক্লোজ ক্যামেরা'}:
        return 'camera_close'
    return None
