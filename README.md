# Zsh Fuzzy File Opener (`ffo`)

This repo provides a small Zsh function that lets you run commands shaped like:

```
ffo <app> <search-command> <search-pattern> <search-directory> [options]
```

It opens an interactive fuzzy picker (via `fzf`) and then opens the selected file(s) in your chosen app/editor.

## Install

1. Put `zsh-fuzzy-file-opener.zsh` somewhere (or clone this repo).
2. Source it from your `~/.zshrc`:

```zsh
source /path/to/zsh-fuzzy-file-opener.zsh
```

## Optional: Zsh completion

This repo includes a completion file at `completions/_ffo`.

Add this to your `~/.zshrc` (adjust the path):

```zsh
fpath=(/path/to/repo/completions $fpath)
autoload -Uz compinit && compinit
```

## Dependencies

- **Required**: `fzf`
- **Recommended**:
  - `fd` (fast filename search for `name` mode)
  - `rg` / `ripgrep` (required for `content` mode; used as fallback for `name`)
  - `bat` (nicer previews; falls back to `sed`)

## Usage

### Filename search (dynamic while you type)

```zsh
ffo nvim name zsh ~/.config
ffo code name README .
ffo default name docker ~/projects
```

### Content search (ripgrep, dynamic while you type)

```zsh
ffo nvim content "TODO|FIXME" ~/src --hidden
ffo code content "useEffect\\(" . --no-ignore
```

- The picker rows are `file:line:col:match...`
- `ffo` will jump to the selected line for editors that support it:
  - `nvim`/`vim`: `+<line>`
  - VS Code: `code --goto file:line:col`

### Git file list (fast in repos)

```zsh
ffo nvim git main .
```

This uses `git ls-files --cached --others --exclude-standard`, so you see tracked + untracked (but not ignored) files.

## Options

Options go after the 4 required positional args.

- **`-d, --max-depth N`**: limit traversal depth (name mode)
- **`--hidden`**: include hidden files (name/content)
- **`--no-ignore`**: do not respect ignore files (name/content)
- **`--follow`**: follow symlinks (name/content)
- **`--git`**: force git mode (same as `mode=git`)
- **`--no-preview`**: disable preview pane
- **`--multi`**: allow multi-select (opens all selections)
- **`--prompt STR`**: override the `fzf` prompt

## Notes / tips

- If you want shorter commands, make aliases in `~/.zshrc`, for example:

```zsh
alias vff='ffo nvim'
alias cff='ffo code'
```

Then:

```zsh
vff name zsh ~/.config
cff content "router" ~/src
```

