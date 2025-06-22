import asyncio
import pdb
import socket
import logging

from playwright.async_api import (
    Playwright,
    Browser as PlaywrightBrowser,
)
from playwright_stealth import stealth_async

from browser_use.browser.browser import Browser, IN_DOCKER
from browser_use.browser.context import BrowserContextConfig
from browser_use.browser.chrome import (
    CHROME_ARGS,
    CHROME_DOCKER_ARGS,
    CHROME_HEADLESS_ARGS,
    CHROME_DISABLE_SECURITY_ARGS,
    CHROME_DETERMINISTIC_RENDERING_ARGS,
)
from browser_use.browser.utils.screen_resolution import (
    get_screen_resolution,
    get_window_adjustments,
)
from .custom_context import CustomBrowserContext

logger = logging.getLogger(__name__)


class CustomBrowser(Browser):

    async def new_context(self, config: BrowserContextConfig | None = None) -> CustomBrowserContext:
        browser_config = self.config.model_dump() if self.config else {}
        context_config = config.model_dump() if config else {}
        merged = {**browser_config, **context_config}
        return CustomBrowserContext(config=BrowserContextConfig(**merged), browser=self)

    async def _setup_builtin_browser(self, playwright: Playwright) -> PlaywrightBrowser:
        assert self.config.browser_binary_path is None, \
            'browser_binary_path должен быть None для встроенных браузеров'

        # Определяем размер окна
        if (not self.config.headless
            and hasattr(self.config, 'new_context_config')
            and hasattr(self.config.new_context_config, 'window_width')
            and hasattr(self.config.new_context_config, 'window_height')
        ):
            screen_size = {
                'width': self.config.new_context_config.window_width,
                'height': self.config.new_context_config.window_height,
            }
            offset_x, offset_y = get_window_adjustments()
        elif self.config.headless:
            screen_size = {'width': 1920, 'height': 1080}
            offset_x, offset_y = 0, 0
        else:
            screen_size = get_screen_resolution()
            offset_x, offset_y = get_window_adjustments()

        # Формируем аргументы Chrome
        chrome_args = {
            f'--remote-debugging-port={self.config.chrome_remote_debugging_port}',
            *CHROME_ARGS,
            *(CHROME_DOCKER_ARGS if IN_DOCKER else []),
            *(CHROME_HEADLESS_ARGS if self.config.headless else []),
            *(CHROME_DISABLE_SECURITY_ARGS if self.config.disable_security else []),
            *(CHROME_DETERMINISTIC_RENDERING_ARGS if self.config.deterministic_rendering else []),
            f'--window-position={offset_x},{offset_y}',
            f'--window-size={screen_size["width"]},{screen_size["height"]}',
            *self.config.extra_browser_args,
        }

        # Убираем конфликтный порт, если он занят
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', self.config.chrome_remote_debugging_port)) == 0:
                chrome_args.remove(f'--remote-debugging-port={self.config.chrome_remote_debugging_port}')

        browser_class = getattr(playwright, self.config.browser_class)
        args_map = {
            'chromium': list(chrome_args),
            'firefox': ['-no-remote', *self.config.extra_browser_args],
            'webkit': ['--no-startup-window', *self.config.extra_browser_args],
        }

        # Запуск браузера с прокси
        browser = await browser_class.launch(
            channel='chromium',
            headless=self.config.headless,
            args=args_map[self.config.browser_class],
            proxy={'server': 'socks5://127.0.0.1:1080'},
            handle_sigterm=False,
            handle_sigint=False,
        )

        # Применяем stealth ко всем новым страницам
        # Оборачиваем метод new_page
        original_new_page = browser.new_page
        async def stealth_new_page(*args, **kwargs):
            page = await original_new_page(*args, **kwargs)
            await stealth_async(page)
            return page

        browser.new_page = stealth_new_page  # type: ignore

        return browser
