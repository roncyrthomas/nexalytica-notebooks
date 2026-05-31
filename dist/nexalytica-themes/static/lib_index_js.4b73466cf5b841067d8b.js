"use strict";
(self["webpackChunknexalytica_themes"] = self["webpackChunknexalytica_themes"] || []).push([["lib_index_js"],{

/***/ "./lib/index.js"
/*!**********************!*\
  !*** ./lib/index.js ***!
  \**********************/
(__unused_webpack_module, __webpack_exports__, __webpack_require__) {

__webpack_require__.r(__webpack_exports__);
/* harmony export */ __webpack_require__.d(__webpack_exports__, {
/* harmony export */   "default": () => (__WEBPACK_DEFAULT_EXPORT__)
/* harmony export */ });
/* harmony import */ var _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__ = __webpack_require__(/*! @jupyterlab/apputils */ "webpack/sharing/consume/default/@jupyterlab/apputils");
/* harmony import */ var _jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0___default = /*#__PURE__*/__webpack_require__.n(_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__);

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
/** Built-in base themes, loaded at runtime before our palette overrides. */
const BASE_DARK = '@jupyterlab/theme-dark-extension/index.css';
const BASE_LIGHT = '@jupyterlab/theme-light-extension/index.css';
const THEMES = [
    { name: 'Nexalytica Default Dark', file: 'nex-default-dark.css', isLight: false },
    { name: 'Nexalytica Default Light', file: 'nex-default-light.css', isLight: true },
    { name: 'Nexalytica Violet Dark', file: 'nex-violet-dark.css', isLight: false },
    { name: 'Nexalytica Violet Light', file: 'nex-violet-light.css', isLight: true },
    { name: 'Nexalytica Sky Dark', file: 'nex-sky-dark.css', isLight: false },
    { name: 'Nexalytica Sky Light', file: 'nex-sky-light.css', isLight: true },
    { name: 'Nexalytica Monochrome Dark', file: 'nex-monochrome-dark.css', isLight: false },
    { name: 'Nexalytica Monochrome Light', file: 'nex-monochrome-light.css', isLight: true }
];
const plugin = {
    id: 'nexalytica-themes:plugin',
    description: 'Nexalytica brand themes.',
    autoStart: true,
    requires: [_jupyterlab_apputils__WEBPACK_IMPORTED_MODULE_0__.IThemeManager],
    activate: (_app, manager) => {
        for (const theme of THEMES) {
            manager.register({
                name: theme.name,
                isLight: theme.isLight,
                themeScrollbars: true,
                load: () => manager
                    .loadCSS(theme.isLight ? BASE_LIGHT : BASE_DARK)
                    .then(() => manager.loadCSS(`${PKG}/${theme.file}`)),
                unload: () => Promise.resolve()
            });
        }
    }
};
/* harmony default export */ const __WEBPACK_DEFAULT_EXPORT__ = (plugin);


/***/ }

}]);
//# sourceMappingURL=lib_index_js.4b73466cf5b841067d8b.js.map