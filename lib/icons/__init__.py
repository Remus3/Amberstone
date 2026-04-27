"""Icon downloader module (DDragon images).

Downloads champion/spell/rune/item icons into data/icons/ using lib.http.
"""
from lib.icons.downloader import IconDownloader, download_all

__all__ = ["IconDownloader", "download_all"]
