import { JupyterFrontEndPlugin } from '@jupyterlab/application';
import { IThemeManager } from '@jupyterlab/apputils';

/**
 * Nexalytica brand themes for JupyterLab / Notebook 7.
 *
 * Each entry registers a named theme in Settings -> Theme. The `load`
 * callback fetches the matching CSS file from this extension's theme
 * directory (served under `api/themes/nexalytica-themes/`). Each CSS file
 * @imports the built-in light/dark base theme for a complete variable set,
 * then overrides only the brand palette.
 */
const PKG = 'nexalytica-themes';

interface NexTheme {
  name: string;
  file: string;
  isLight: boolean;
}

/** Built-in base themes, loaded at runtime before our palette overrides. */
const BASE_DARK = '@jupyterlab/theme-dark-extension/index.css';
const BASE_LIGHT = '@jupyterlab/theme-light-extension/index.css';

const THEMES: NexTheme[] = [
  { name: 'Nexalytica Default Dark', file: 'nex-default-dark.css', isLight: false },
  { name: 'Nexalytica Default Light', file: 'nex-default-light.css', isLight: true },
  { name: 'Nexalytica Violet Dark', file: 'nex-violet-dark.css', isLight: false },
  { name: 'Nexalytica Violet Light', file: 'nex-violet-light.css', isLight: true },
  { name: 'Nexalytica Sky Dark', file: 'nex-sky-dark.css', isLight: false },
  { name: 'Nexalytica Sky Light', file: 'nex-sky-light.css', isLight: true },
  { name: 'Nexalytica Monochrome Dark', file: 'nex-monochrome-dark.css', isLight: false },
  { name: 'Nexalytica Monochrome Light', file: 'nex-monochrome-light.css', isLight: true }
];

const plugin: JupyterFrontEndPlugin<void> = {
  id: 'nexalytica-themes:plugin',
  description: 'Nexalytica brand themes.',
  autoStart: true,
  requires: [IThemeManager],
  activate: (_app, manager: IThemeManager): void => {
    for (const theme of THEMES) {
      manager.register({
        name: theme.name,
        isLight: theme.isLight,
        themeScrollbars: true,
        load: () =>
          manager
            .loadCSS(theme.isLight ? BASE_LIGHT : BASE_DARK)
            .then(() => manager.loadCSS(`${PKG}/${theme.file}`)),
        unload: () => Promise.resolve()
      });
    }
  }
};

export default plugin;
