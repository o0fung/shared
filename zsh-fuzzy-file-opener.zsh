#!/usr/bin/env zsh
# Zsh fuzzy file opener: fd/rg/git + fzf + opener/editor
#
# Source this file from ~/.zshrc:
#   source /path/to/zsh-fuzzy-file-opener.zsh
#
# Provides:
#   ffo <app> <mode> <pattern> <dir> [options]
#
# Modes:
#   name     - fuzzy filename search (fd/rg --files)
#   content  - ripgrep content search (dynamic as you type)
#   git      - search files from `git ls-files` (fast in repos)
#
# Options (after the 4 positional args):
#   -d, --max-depth N    limit directory traversal depth
#   --hidden             include hidden files (fd/rg modes)
#   --no-ignore          do not respect ignore files (fd/rg modes)
#   --follow             follow symlinks (fd/rg modes)
#   --git                force git mode (same as mode=git)
#   --no-preview         disable fzf preview window
#   --multi              allow multi-select (opens all)
#   --prompt STR         override fzf prompt
#
# Notes:
# - Requires `fzf` for interactive selection.
# - Uses `fd` if available for name search; falls back to `rg --files`.
# - Uses `bat` for preview if available; falls back to `sed`.

function ffo() {
  emulate -L zsh
  setopt pipefail no_aliases

  local app="${1-}"
  local mode="${2-}"
  local initial_query="${3-}"
  local dir="${4-}"
  shift 4 2>/dev/null || true

  if [[ -z "$app" || -z "$mode" || -z "$initial_query" || -z "$dir" || "$app" == "-h" || "$app" == "--help" || "$mode" == "-h" || "$mode" == "--help" ]]; then
    _ffo_help
    return 2
  fi

  if [[ ! -d "$dir" ]]; then
    print -u2 "ffo: directory not found: $dir"
    return 2
  fi
  # Canonicalize to absolute path so pickers/open/preview work regardless of cwd.
  dir="${dir:A}"

  local -a opt_hidden opt_noignore opt_follow opt_depth opt_nopreview opt_multi opt_prompt opt_git opt_help
  zparseopts -E -D -- \
    hidden=opt_hidden \
    no-ignore=opt_noignore \
    follow=opt_follow \
    d:=opt_depth max-depth:=opt_depth \
    no-preview=opt_nopreview \
    multi=opt_multi \
    prompt:=opt_prompt \
    git=opt_git \
    help=opt_help h=opt_help || true

  if (( ${#opt_help} )); then
    _ffo_help
    return 0
  fi

  local depth=""
  if (( ${#opt_depth} )); then
    # zparseopts stores as: (-d 5) or (--max-depth 5)
    depth="${opt_depth[2]-}"
  fi

  if (( ${#opt_git} )); then
    mode="git"
  fi

  if ! command -v fzf >/dev/null 2>&1; then
    print -u2 "ffo: missing dependency: fzf"
    print -u2 "ffo: install fzf, then retry"
    return 127
  fi

  local preview_cmd=""
  if (( ${#opt_nopreview} )); then
    preview_cmd=""
  else
    preview_cmd='$(_ffo_preview {})'
  fi

  local prompt="ffo> "
  if (( ${#opt_prompt} )); then
    prompt="${opt_prompt[2]-$prompt}"
  else
    case "$mode" in
      name) prompt="name> " ;;
      content) prompt="content> " ;;
      git) prompt="git> " ;;
      *) prompt="ffo> " ;;
    esac
  fi

  local -a fzf_common
  fzf_common=(
    --height=80%
    --layout=reverse
    --border
    --prompt "$prompt"
    --query "$initial_query"
    --cycle
  )
  if [[ -n "$preview_cmd" ]]; then
    fzf_common+=( --preview "$preview_cmd" --preview-window=right:60%:wrap )
  fi
  if (( ${#opt_multi} )); then
    fzf_common+=( --multi )
  fi

  local selection=""
  case "$mode" in
    name)
      selection="$(_ffo_pick_name "$dir" "$depth" "$opt_hidden" "$opt_noignore" "$opt_follow" "${fzf_common[@]}")" || return $?
      ;;
    content)
      selection="$(_ffo_pick_content "$dir" "$opt_hidden" "$opt_noignore" "$opt_follow" "${fzf_common[@]}")" || return $?
      ;;
    git)
      selection="$(_ffo_pick_git "$dir" "${fzf_common[@]}")" || return $?
      ;;
    *)
      print -u2 "ffo: unknown mode: $mode (use: name|content|git)"
      return 2
      ;;
  esac

  [[ -z "$selection" ]] && return 0

  # Open selected entries (handles multi-select by splitting on newlines).
  local IFS=$'\n'
  local -a lines
  lines=(${(f)selection})

  local line file col
  for line in "${lines[@]}"; do
    if [[ "$mode" == "content" ]]; then
      # rg format: path:line:col:match...
      file="${line%%:*}"
      local rest="${line#*:}"
      local line_no="${rest%%:*}"
      rest="${rest#*:}"
      col="${rest%%:*}"
      [[ "$file" == /* ]] || file="$dir/$file"
      _ffo_open "$app" "$file" "$line_no" "$col"
    else
      local path="$line"
      [[ "$path" == /* ]] || path="$dir/$path"
      _ffo_open "$app" "$path" "" ""
    fi
  done
}

function _ffo_help() {
  cat <<'EOF'
ffo - fuzzy file opener (zsh)

Usage:
  ffo <app> <mode> <pattern> <dir> [options]

Examples:
  ffo nvim name zsh ~/.config
  ffo code name README .
  ffo nvim content "TODO|FIXME" ~/src --hidden
  ffo code content "useEffect\\(" . --no-ignore
  ffo nvim git main .

Modes:
  name       fuzzy filename search (fd/rg --files)
  content    ripgrep content search (dynamic as you type)
  git        search files from `git ls-files` (fast in repos)

Options:
  -d, --max-depth N    limit traversal depth (name mode)
  --hidden             include hidden files (name/content)
  --no-ignore          ignore ignore-files (.gitignore, etc) (name/content)
  --follow             follow symlinks (name/content)
  --git                force git mode (same as mode=git)
  --no-preview         disable preview pane
  --multi              multi-select (opens all)
  --prompt STR         override fzf prompt

Notes:
  - Requires: fzf
  - Recommended: fd, rg, bat
EOF
}

function _ffo_has() {
  command -v "$1" >/dev/null 2>&1
}

function _ffo_preview() {
  emulate -L zsh
  local path="$1"
  [[ -z "$path" ]] && return 0

  # If selection is a content-search row "file:line:col:...", take first field.
  local file="${path%%:*}"
  if [[ -f "$file" ]]; then
    if _ffo_has bat; then
      bat --style=numbers --color=always --line-range :200 -- "$file" 2>/dev/null || true
    else
      sed -n '1,200p' -- "$file" 2>/dev/null || true
    fi
  elif [[ -f "$path" ]]; then
    if _ffo_has bat; then
      bat --style=numbers --color=always --line-range :200 -- "$path" 2>/dev/null || true
    else
      sed -n '1,200p' -- "$path" 2>/dev/null || true
    fi
  fi
}

function _ffo_pick_name() {
  emulate -L zsh
  setopt pipefail

  local dir="$1"
  local depth="$2"
  local opt_hidden_arr="$3"
  local opt_noignore_arr="$4"
  local opt_follow_arr="$5"
  shift 5

  local hidden_flag=""
  local noignore_flag=""
  local follow_flag=""
  [[ -n "$opt_hidden_arr" ]] && hidden_flag="--hidden"
  [[ -n "$opt_noignore_arr" ]] && noignore_flag="--no-ignore"
  [[ -n "$opt_follow_arr" ]] && follow_flag="--follow"

  local depth_flag=""
  if [[ -n "$depth" ]]; then
    depth_flag="--max-depth $depth"
  fi

  local list_cmd=""
  if _ffo_has fd; then
    # Let fzf do the interactive fuzzy matching; fd just enumerates files.
    list_cmd="fd --type f --color=never $hidden_flag $noignore_flag $follow_flag $depth_flag --exclude .git -- . ${(q)dir} 2>/dev/null || true"
  else
    list_cmd="rg --files $hidden_flag $noignore_flag ${(q)dir} 2>/dev/null || true"
  fi

  FZF_DEFAULT_COMMAND="$list_cmd" \
  fzf "$@"
}

function _ffo_pick_git() {
  emulate -L zsh
  setopt pipefail
  local dir="$1"
  shift

  if ! _ffo_has git; then
    print -u2 "ffo: missing dependency for git mode: git"
    return 127
  fi

  local top=""
  top="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null)" || {
    print -u2 "ffo: not a git repo: $dir"
    return 2
  }

  (cd "$top" && git ls-files --cached --others --exclude-standard) \
    | while IFS= read -r p; do print -r -- "$top/$p"; done \
    | fzf "$@"
}

function _ffo_pick_content() {
  emulate -L zsh
  setopt pipefail

  local dir="$1"
  local opt_hidden_arr="$2"
  local opt_noignore_arr="$3"
  local opt_follow_arr="$4"
  shift 4

  if ! _ffo_has rg; then
    print -u2 "ffo: missing dependency for content mode: rg (ripgrep)"
    return 127
  fi

  local hidden_flag=""
  local noignore_flag=""
  local follow_flag=""
  [[ -n "$opt_hidden_arr" ]] && hidden_flag="--hidden"
  [[ -n "$opt_noignore_arr" ]] && noignore_flag="--no-ignore"
  [[ -n "$opt_follow_arr" ]] && follow_flag="--follow"

  local reload_cmd
  reload_cmd="rg --column --line-number --no-heading --color=always --smart-case $hidden_flag $noignore_flag $follow_flag -- {q} ${(q)dir} 2>/dev/null || true"

  # `--disabled` prevents fzf from filtering our ANSI rg output; `--phony` + reload drives results.
  # Preview: show matches in the selected file (field 1 before ':')
  fzf --ansi --disabled --phony \
    --delimiter : \
    --bind "change:reload:$reload_cmd" \
    --bind "start:reload:$reload_cmd" \
    --preview 'rg --color=always -n --smart-case -- {q} {1} 2>/dev/null || true' \
    "$@"
}

function _ffo_open() {
  emulate -L zsh
  local app="$1"
  local file="$2"
  local line="$3"
  local col="$4"

  if [[ "$app" == "default" ]]; then
    if _ffo_has xdg-open; then
      xdg-open -- "$file" >/dev/null 2>&1 &
      return 0
    elif _ffo_has open; then
      open -- "$file" >/dev/null 2>&1 &
      return 0
    fi
  fi

  case "$app" in
    code|code-insiders)
      if [[ -n "$line" ]]; then
        "$app" --goto "$file:$line:${col:-1}" >/dev/null 2>&1 &
      else
        "$app" "$file" >/dev/null 2>&1 &
      fi
      ;;
    nvim|vim)
      if [[ -n "$line" ]]; then
        "$app" "+${line}" -- "$file"
      else
        "$app" -- "$file"
      fi
      ;;
    subl|sublime_text)
      if [[ -n "$line" ]]; then
        "$app" "$file:$line:${col:-1}" >/dev/null 2>&1 &
      else
        "$app" "$file" >/dev/null 2>&1 &
      fi
      ;;
    less|bat|cat)
      "$app" -- "$file"
      ;;
    *)
      "$app" -- "$file"
      ;;
  esac
}

