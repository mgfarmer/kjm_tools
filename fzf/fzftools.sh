[ -f ~/.fzf.bash ] && source ~/.fzf.bash

fhelp() {
    echo "cdp           : select and goto a parent folder"
    echo "cdc           : select and goto any child folder"
    echo "cdi           : select and goto immediate child folder"
    echo "cdrr          : cd to the current repo root"
    echo "cdrepo        : cd to selected repo"
    echo "ch            : search and execute command from history"
}

# cd-parent: cd to any parent folder in the current path
cdp() {
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

# cd-child: select and goto any child folder
cdc() {
  local dir
  dir=$(find . -path '*/\.*' -prune \
                  -o -type d -print 2> /dev/null | fzf -1 +m) &&
  cd "$dir"
}

# cd-immediate-child: select and goto immediate child folder.  
cdi() {
  local dir
  local qs="$1"
  dir=$(find . -maxdepth 1 -path '*/\.*' -prune \
                  -o -type d -print 2> /dev/null | fzf -1 -e +m --query="${qs}") &&
  cd "$dir"
}

# cd-repo: cd to a repo
# assumes you keep all your git repo clones in a single folder (like ~/git)
# if you put them elsewhere, you'll need to edit this function
cdrepo() {
  local dir
  local qs="$1"
  dir=$(find ~/git/ -maxdepth 1 -path '*/\.*' -prune \
                  -o -type d -print 2> /dev/null | fzf -1 -e +m --query="${qs}") &&
  cd "$dir"
}

# get the current repo root folder name
_up_to_repo () { 
    # cd up to the repo root folder
    local p=${PWD}
    # echo $p
    while ! [ -d ${p}/.git ]; do
        p="$(dirname "$p")";
        if [[ "${p}" == "/" ]]; then
            >&2 echo "You are not in a git repo..."
            echo "."
            return ;
        fi
    done
    echo ${p}
}

# cd to the current repo root
cdrr () {
    cd $(_up_to_repo)
}

ch() {
  eval $( ([ -n "$ZSH_NAME" ] && fc -l 1 || history) | fzf +s --tac | sed -E 's/ *[0-9]*\*? *//' | sed -E 's/\\/\\\\/g')
}
