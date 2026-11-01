import os
from pathlib import Path
import sys


def resource_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))


def vendor_root():
    default = resource_root() / 'vendor'
    if getattr(sys, 'frozen', False) and sys.platform == 'darwin':
        default = Path(sys.executable).resolve().parents[1] / 'Resources/vendor'
    return Path(os.environ.get('ANY2PDF_VENDOR', default))


def data_root():
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    root = base / 'Any2PDF'
    root.mkdir(parents=True, exist_ok=True)
    return root
