gff() {

    # Declare an array of handy shortcuts. The key can be provided
    # on the command line as the <search_dir> and the full path
    # will be substituted.  Add as many as you want.
    #
    # Each shortcut consists of up to three fields, separated 
    # by commas.  The fields are:
    #
    # 1. (required) the base folder name to be searched
    # 2. (optional) an initial query string for fzf 
    # 3. (optional) a host name to search on
    #
    declare -A loc_keys
    loc_keys["compiler"]="/nfs/teams/sw/share/compiler/releases/"
    loc_keys["ip"]="/nfs/teams/ret/share/release/"
    loc_keys["fs"]="/nfs/teams/sw/static/dev-tools/freedom-studio/"
    loc_keys["fsorca"]="/nfs/teams/sw/static/dev-tools/freedom-studio/orca/sifive-internal, .zip .gz, kevinm@login.sifive.com"
    loc_keys["ft"]="/nfs/teams/sw/static/dev-tools/freedom-tools/"
    loc_keys["cxdoc"]="/nfs/teams/cx/share/documentation/"
    loc_keys["fusdk"]="/nfs/teams/sw/share/fusdk/"
    loc_keys["alg"]="/nfs/teams/sw/share/lib/"
    loc_keys["octane"]="/nfs/teams/sw/share/octane/"
    loc_keys["dl"]="~/Downloads"
    loc_keys["scratch"]="/scratch/kevinm, , remote"

    function usage() {
cat << EndOfUsage        
A fuzzy file finder for remote(ssh) and local folders.

Usage: gff [-reEsh] [-m maxdepth] [-q querystring] [-r <search_host>] <search_dir> [<subdir>]

  -e : extract the package if it is a recognized archive
  -E : like -e, but delete the archive after extraction
  -s : Usually entries are sorted by last mode date. This
       flags turns off sorting by date.

  -m maxdepth : Default is ${maxdepth}, so only files up to six levels
     deep are shown.  This is primarily for speed and decluttering.
     You can specify deeper, or shallower, if you want.

  -q querystring
     Default is ${query_str}. This is the initial string for 
     the search query.  For instance, if you know you're looking 
     for zip files, use '-q .zip'

  -h remote_host 
     Overide the default remote host (which is '${search_host}').
     Use this if the file system you need does not exist on the default
     remote host (for instance '/scratch' ).  You can change the default 
     remote host by editing this bash function. This can be a host entry 
     in your .ssh/config file (which makes things easy) or you can simply
     use "<user>@<host>"

<search_dir> is the root directory to search from.  <search_dir>
can be a fully qualified filename, and it will be downloaded without
opening the search pane.

If the <search_dir> exists on the local system (where you are using
this script) then a local search will be done.  If you really want
to a remote search using the same <search_dir> then use the '-r'
flag to force a remote search.

<subdir> is an optional subfolder path applied to the main
<search_dir> (as <search_dir>/<subdir>).  This is useful in shortcuts
where a shortcut defines a top level folder path, but you want to
drill down a bit more when using the shortcut.

Shortcuts are easy to remember keys for common search paths that
you use.  Add or remove shortcuts by editing this script.  It's easy.

Each shortcut consists of up to three fields, separated 
by commas.  The fields are:

1. (required) the base folder name to be searched
2. (optional) an initial query string for fzf, can include spaces
3. (optional) a host name to search on

The following shortcut keywords are currently configured:

EndOfUsage

        for key in ${!loc_keys[@]}; do
            printf "  %-8s => %s\n" ${key} "${loc_keys[${key}]}"
        done
        return
    }

    local extract=0
    local delete=0
    local sort=1
    local maxdepth=6
    local force_remote=0
    local query_str=""
    local query_ovr=0

    # This is the default <remote-host> to use if none is specifed
    # on the command line.  I suggest using an dedicated entry from
    # your .ssh/config file, like this:
    #
    # Host remote
    #   ProxyCommand ssh -q -l %r login.sifive.com nc -q0 sw01 %p
    #   User kevinm
    #   IdentityFile ~/.ssh/id_rsa_s5
    #
    # Specifying the actual host on the ProxyCommand line (sw01 in
    # this example.) (note, my config has an sw01 alias, but it sets
    # up tunnels and other things not required here, so I have this
    # separate 'remote' entry dedicated for this)
    local search_host=remote
    local host_ovr=0

    local OPTIND o
    while getopts "leEsm:q:rh:" o; do
        case "${o}" in
            e)
                extract=1
                ;;
            E)
                extract=1
                delete=1
                ;;
            s)
                sort=0
                ;;
            m)
                maxdepth=${OPTARG}
                ;;
            r)
                force_remote=1
                ;;
            q)
                query_str="\"${OPTARG}\""
                query_ovr=1
                ;;
            h)
                search_host="${OPTARG}"
                host_ovr=1
                ;;
            *)
                usage
                return
                ;;
        esac
    done
    shift $((OPTIND-1))


    # If you do most of your searching on a local machine, you can do this:
    #
    #  local search_host=$(hostname)
    # 
    # You can still do remote search/fecth by specifying the remote host 
    # on the command line

    # Check that fzf is available
    if ! command -v fzf &> /dev/null
    then
        echo "This script requires 'fzf' to work but 'fzf'"
        echo "could not be found. Please install it and put"
        echo "it on the path."
        return
    fi

    if [ "$#" -eq 0 ]; then
        echo "No folder or shortcut provided!"
        usage
        return
    fi

    # Expand ~'s in folder names'
    # https://stackoverflow.com/a/29310477/45206
    expandPath() {
    case $1 in
        ~[+-]*)
        local content content_q
        printf -v content_q '%q' "${1:2}"
        eval "content=${1:0:2}${content_q}"
        printf '%s\n' "$content"
        ;;
        ~*)
        local content content_q
        printf -v content_q '%q' "${1:1}"
        eval "content=~${content_q}"
        printf '%s\n' "$content"
        ;;
        *)
        printf '%s\n' "$1"
        ;;
    esac
    }

    # trim leading/trailing whitespace
    # https://stackoverflow.com/a/3352015/45206
    trim() {
        local var="$*"
        # remove leading whitespace characters
        var="${var#"${var%%[![:space:]]*}"}"
        # remove trailing whitespace characters
        var="${var%"${var##*[![:space:]]}"}"
        printf '%s' "$var"
    }
    
    # Parse csv strings, removing leading and trailing whitespace while
    # preserving embedded white space.  Call as:
    #   parse_csv <array> <string>
    #
    parse_csv() {
        local -n farr=$1
        # tokenize the shortcut using comma seperator, we cannot
        # include a <space> in the IFS value because that will 
        # cause whitespace in the search terms to be lost.
        set -f; IFS="," read -a fields <<<"${2}"; set +f

        # now strip leading/railing white space from
        # tokens, building a new array of the results
        for (( i=0; i<${#fields[@]}; i++ )); do 
            #echo "$i  ${fields[$i]}"
            farr[$i]=$(trim "${fields[$i]}")
        done
    }

    local is_local=0

    if [ ${search_host} == $(hostname) ]; then is_local=1; fi

    local search_dir=${1}
    local subdir=${2}

    # If a shortcut was provided, find and substitute the full path.
    for key in ${!loc_keys[@]}; do
        if [ ${search_dir} == ${key} ]; then
            local fa=( )
            parse_csv fa ${loc_keys[${key}]}

            echo "Using shortcut: ${key} => ${fa[0]}"

            # Apply the base folder, using expandPath allows
            # shortcut paths to use "~/<path>"
            search_dir=$(expandPath ${fa[0]})

            # Apply the query terms, unless overridden on the command line
            local qs=${fa[1]}
            if [ ${query_ovr} -eq 0 ] && ! [ "${qs}" == "" ]; then
                query_str="\"${qs}\""
            fi

            # Apply the search host, unless overridden on the command line
            local ho=${fa[2]}
            if [ ${query_ovr} -eq 0 ] && ! [ "${ho}" == "" ]; then
                search_host="\"${ho}\""
            fi

            break
        fi
    done

    # apply a subdir, if provided
    local subdir=${2}
    if ! [ "${subdir}" == "" ]; then
        search_dir=${search_dir}/${subdir}
    fi

    if ( [ -d ${search_dir} ]  || [ -f ${search_dir} ] ) && [ ${force_remote} -eq 0 ]; then is_local=1; fi

    local remote_file
    local looks_like_a_file=false
    if [[ ${search_dir} =~ .*\.[a-zA-Z0-9]+ ]]; then
        looks_like_a_file=true
        remote_file=${search_dir}
        #echo "Looks like a file: ${search_dir}"
    fi

    # Mysterious magical things happen here...
    #
    # - Hidden folders are skipped
    # - Displayed paths are relative to the <remote_root> folder
    # - entries are sorted by last modification date with the
    #   date being diplayed.
    # - Search the list by typing terms (see fzf man page)
    # - Use the arrow keys to navigate the list
    # - Hit ESC to exit without doing anything (i.e. abort)
    #

    if [ "${remote_file}" == "" ]; then
        local dir
        
        local sort_cmd="tee"
        if [ ${sort} -eq 1 ]; then sort_cmd="sort -n -r"; fi

        local find_cmd
        local shell_cmd
        local formatter="%TY-%Tm-%Td %Tl:%TM%Tp  %12s %p\n"

        local host=${search_host}
        if [ ${is_local} -eq 1 ]; then
            host=$(hostname)
        fi

        fzf_params="--exit-0 --header=\"(${host}) Searching: ${search_dir}\""

        local fzf_command="fzf +s +m --query=${query_str} ${fzf_params}"
        if [ ${is_local} -eq 1 ]; then
            find_cmd="find . -maxdepth ${maxdepth} -type f ! -path \"*/.*\" -printf \"${formatter}\" 2> /dev/null"
            shell_cmd="pushd ${search_dir} >/dev/null && ${find_cmd} | ${sort_cmd} | ${fzf_command} && popd >/dev/null"
        else 
            find_cmd="find . -maxdepth ${maxdepth} -type f ! -path \\\"*/.*\\\" -printf \\\"${formatter}\\\" 2> /dev/null"
            shell_cmd="ssh ${search_host} \"cd ${search_dir} && ${find_cmd} | ${sort_cmd}\" | ${fzf_command}"
        fi

        #echo ${shell_cmd} && return

        dir=$(eval ${shell_cmd})
        if [ $? -eq 130 ]; then
            return
        fi

        if [ "${dir}" == "" ]; then
            echo "checking to see if it is a file..."
            if [ ${is_local} -eq 1 ]; then
                dir=$([[ -f ${search_dir} ]] && echo "${search_dir}")
            else 
                dir=$(ssh ${search_host} "[[ -f ${search_dir} ]] && echo \"${search_dir}\"")
            fi
            # Nothing selected, op aborted!
            if [ "${dir}" == "" ]; then 
                echo "No results! Check your query..."
                return
            fi
            remote_file=${dir}
        else
            # Third field in the find output is the filename
            local tokens=( $dir ) 
            remote_file=${search_dir}/${tokens[3]}
        fi
    fi

    local same_file=0

    local copy_cmd="scp ${search_host}:${remote_file} ."
    local copy_msg="Downloading: ${search_host}:${remote_file}..."
    if [ ${is_local} -eq 1 ]; then
        # Check to see if the selected file is present in the same folder.
        if [ "$(stat -L -c %d:%i ${remote_file})" = "$(stat -L -c %d:%i ./$(basename ${remote_file}) 2> /dev/null)" ]; then
            copy_cmd=""
            same_file=1
        else
            copy_cmd="cp ${remote_file} ."
            copy_msg="Copying ${remote_file} to here..."
        fi
    fi

    echo "${copy_msg}"
    eval ${copy_cmd}

    # If the fetch failed, remove any partial download/copy and exit.
    if [ $? -ne 0 ]; then
        if [ -f ./$(basename ${remote_file}) ]; then
            rm ./$(basename ${remote_file})
        fi
        return
    fi

    local local_file="$(basename ${remote_file})"
    
    local extracted=0

    if [ ${extract} -eq 1 ]; then
        local extractors=()
        extractors+=("*.tar.gz,  tar xzf")
        extractors+=("*.tgz,     tar xzf")
        extractors+=("*.tar,     tar xf")
        extractors+=("*.gz,      gunzip")
        extractors+=("*.zip,     unzip -o")
        extractors+=("*.7z,      7z x -aoa")


        for extractor in ${!extractors[@]}; do
            local ex=()
            parse_csv ex "${extractors[${extractor}]}"
            if [ ${local_file} = ${ex[0]} ]; then
                if ! [ -x "$(command -v ${ex[1]})" ]; then
                    echo "\"${ex[1]}\" not found.  Please install it, if needed, and"
                    echo "put it on your path."
                    return
                fi
                # Do the extraction!
                echo "Extracting ${local_file}..."
                eval ${ex[1]} ${local_file} && extracted=1
            fi
        done

        if [ ${extracted} -eq 1 ] && [ ${delete} -eq 1 ]; then
            if [ $same_file -eq 1 ]; then
                echo "Not deleting ${local_file} because it is the source file."
            else
                echo "Removing ${local_file}"
                rm ${local_file}
            fi
        fi
    else
        # Just ls the local file for the user
        ls -l ${local_file}
    fi

    return
}