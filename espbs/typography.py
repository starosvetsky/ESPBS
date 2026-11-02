"""Local Medeo fonts for the legacy Windows/Tk interface."""
import os
from pathlib import Path


def configure_tk(root):
    from tkinter import font, ttk
    if os.name == 'nt':
        import ctypes
        directory = Path(__file__).with_name('web') / 'fonts'
        for name in ('MedeoSans-Regular.ttf', 'MedeoSans-Bold.ttf', 'MedeoMono-Regular.ttf'):
            path = directory / name
            if path.is_file():
                ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0)
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont',
                 'TkCaptionFont', 'TkSmallCaptionFont', 'TkIconFont', 'TkTooltipFont'):
        font.nametofont(name, root=root).configure(family='Medeo Sans')
    font.nametofont('TkFixedFont', root=root).configure(family='Medeo Mono')
    root.option_add('*Font', 'TkDefaultFont')
    ttk.Style(root).configure('.', font='TkDefaultFont')
