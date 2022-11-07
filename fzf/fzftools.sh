[ -f ~/.fzf.bash ] && source ~/.fzf.bash

fhelp() {
    echo "fdp           : select and goto a parent folder"
    echo "fd            : select and goto child folder"
    echo "cdr           : cd to the current repo root"
    echo "fdr           : select and goto child of current repo root"
    echo "fh            : search and execute command from history"
    echo "getip         : seach and download IP package from RMT"
}

fdp() {
  local declare dirs=()
  get_parent_dirs() {
    if [[ -d "${1}" ]]; then dirs+=("$1"); else return; fi
    if [[ "${1}" == '/' ]]; then
      for _dir in "${dirs[@]}"; do echo $_dir; done
    else
      get_parent_dirs $(dirname "$1")
    fi
  }
  local DIR=$(get_parent_dirs $(realpath "${1:-$PWD}") | fzf-tmux --tac)
  cd "$DIR"
}

fd() {
  local dir
  dir=$(find ${1:-.} -path '*/\.*' -prune \
                  -o -type d -print 2> /dev/null | fzf +m) &&
  cd "$dir"
}

# get the current repo root folder name
up_to_repo () { 
    # cd up to the repo root folder
    local p=${PWD}
    while ! [ -d ${p}/.git ]; do
        p="$(dirname "$p")";
        if [ "${p}" == "/" ]; then
            >&2 echo "You are not in a git repo..."
            echo "."
            return;
        fi
    done
    echo ${p}
}

# cd to the current repo root
cdr () {
    cd $(up_to_repo)
}

# fzf cd from currentrepo root
fdr () {
    fd $(up_to_repo)
}

fh() {
  eval $( ([ -n "$ZSH_NAME" ] && fc -l 1 || history) | fzf +s --tac | sed -E 's/ *[0-9]*\*? *//' | sed -E 's/\\/\\\\/g')
}

getip() {
  local dir
  local tokens
  dir=$(ssh sw01 "find /nfs/teams/ret/share/release -name \*.gz \
                  -printf \"%Tx %p\n\" 2> /dev/null" | sort -n -r | fzf +s +m) && \
        tokens=( $dir ) && scp sw01:${tokens[1]} .
}
