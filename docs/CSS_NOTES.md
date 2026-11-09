# CSS notes for the web shell

Scope: `backend/web/static/web/app.css` (styles) and `theme.js` (theme choice and collapsed
sidebar). Written from reading those two files; nothing here was run.

## How colours work

- Every colour is a custom property on `:root` (`--bg`, `--panel`, `--text`, `--accent`, ...).
  Dark is the default.
- Light values live in **two places that must stay identical**: `:root[data-theme="light"]`
  (the user picked Light) and the `@media (prefers-color-scheme: light)` block for
  `:root:not([data-theme="dark"])` (the user picked System and the OS is light).
  Change a light colour in both.
- `theme.js` sets or removes `data-theme` on `<html>` and remembers the choice in
  `localStorage` (`jth-theme`). "System" means no `data-theme` attribute.
- Do not add new hex colours in rules. Add a token to all three palette blocks and use
  `var(--name)`. The only literals outside the palettes today are `#fff` on accent/danger
  backgrounds and the shadow colours.

## Layout and naming

- `.shell` is the page: `.side` (sticky 240px sidebar) plus `.main` (`.top` bar, then `.page`).
- Class names are short on purpose (`.ni` nav item, `.mi` menu item, `.kc` kanban card).
  Reuse an existing one before adding another.
- `body.collapsed` shrinks the sidebar to 68px and hides labels (`.lbl`, `.foot`, `.badge`).
- Breakpoints: 1100px (stats and detail grids shrink) and 760px (sidebar stacks above content).

## Conventions to keep

- Main controls (`.btn`, `.search`, `select`, `.tog a`) are 44px tall; chips and kanban
  selects are 36px.
- Keyboard focus uses one shared `:focus-visible` outline (`--accent-line`). Do not remove it.
- Check every change in Dark, Light and System (with the OS set each way).
