gff() {

    function usage() {    
cat << EndOfUsage        
A fuzzy file finder for remote(ssh) and local folders.

Configuration:

    gff looks for a configuration file in these places, using the
    first one found:

      ~/.config/gff/config
      ~/.gff_config (note: this is a hidden file with a '.' prefix)

    Use the one included in this repo folder as a template.

    This config file defines the remote host to use, and your
    list of custom shortcuts, and other optional settings.

Usage: gff [-reEshfa] [-m maxdepth] [-q querystring] [-r <search_host>] <search_dir> [<subdir>]

  -e : extract the package if it is a recognized archive
  -E : like -e, but delete the archive after extraction
  -s : Usually entries are sorted by last mode date. This
       flags turns off sorting by date.
  -f : force treat as file. Use when trying to download a
       file directly, where the filename does not have an extension
  -a : show hidden files and folder too.  They are filtered by default

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

RUNNING ON WINDOWS 

It can be done!

You can, of course, run it in a WSL Linux instance. But you can
also run it from a Windows command prompt or powershell.  A WSL
linux installation is still required, but you don't have to start
a Linux terminal to run it, but some setup is required:

1. Setup a WSL Ubuntu instance
2. Clone/copy this script into that instance
3. Modify your .bashrc to source this script on login.
4. Install fzf: sudo apt install fzf
5. Set up ssh access to the remote machines in WSL

Windows provides a "native" bash.exe in the System32 directory that
can be used to run this script.  The first time you run it, it may
take a while because Windows is spinning up the Ubuntu machine in 
the background.  You can run it like:

  C:\Windows\System32\bash.exe -i -c "gff <params>"

But that is too cumbersome.  So there is also a gff.cmd file you
can install into a folder on your path. Which can be run as:

  gff <params>

SHORTCUTS

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

    local extract=false
    local askExtract=true
    local delete=false
    local sort=true
    local maxdepth=6
    local force_remote=false
    local force_is_a_file=false
    local query_str=""
    local query_ovr=false
    local looks_like_a_file=false
    local filter_hidden=true
    local host_ovr=false

    if [ -f ~/.config/gff/config ]; then
        source ~/.config/gff/config
    elif [ -f ~/.gff_config ]; then
        source ~/.gff_config
    else
        echo "No gff_config file found!"
        echo "Looked for:"
        echo "  ~/.config/gff_config"
        echo "  ~/.gff_config"
        echo "  ./gff_config (where this script is located)"
        echo ""
        usage
        return
    fi
    
    local OPTIND o
    while getopts "afleEsm:q:rh:" o; do
        case "${o}" in
            e)
                extract=true
                ;;
            E)
                extract=true
                delete=true
                ;;
            s)
                sort=false
                ;;
            m)
                maxdepth=${OPTARG}
                ;;
            r)
                force_remote=true
                ;;
            q)
                query_str="\"${OPTARG}\""
                query_ovr=true
                ;;
            h)
                search_host="${OPTARG}"
                host_ovr=true
                ;;
            f)
                looks_like_a_file=true
                ;;
            a)
                filter_hidden=false
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

    local is_local=false

    if [ ${search_host} == $(hostname) ]; then is_local=true; fi

    local search_dir=${1}
    local subdir=${2}

    # If a shortcut was provided, find and substitute the full path.
    for key in ${!loc_keys[@]}; do
        if [ ${search_dir} == ${key} ]; then
            local fa=( )
            parse_csv fa "${loc_keys[${key}]}"

            echo "Using shortcut: ${key} => ${fa[0]}"

            # Apply the base folder, using expandPath allows
            # shortcut paths to use "~/<path>"
            search_dir=$(expandPath ${fa[0]})

            # Apply the query terms, unless overridden on the command line
            local qs=${fa[1]}
            if ! ${query_ovr} && ! [ "${qs}" == "" ]; then
                query_str="\"${qs}\""
            fi

            # Apply the search host, unless overridden on the command line
            local ho=${fa[2]}
            if ! ${host_ovr} ] && ! [ "${ho}" == "" ]; then
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

    if ( [ -d ${search_dir} ]  || [ -f ${search_dir} ] ) && ! ${force_remote}; then is_local=true; fi

    local remote_file

    # Check to see if the search_dir looks like an explicit filename (i.e. not a folder name)
    if ${looks_like_a_file}; then
        remote_file=${search_dir}
    elif ${is_local}; then
        if [ -f ${search_dir} ]; then
            # For local use we can simply test if it is a file directly
            remote_file=${search_dir}
        fi
    elif [[ $(basename ${search_dir}) =~ .*\.[a-zA-Z0-9]{1,5} ]]; then
        # This is not 100% reliable...but should handle close to 100% of cases...
        # But is is faster than a separate ssh command to test for it.
        #
        # Check to see if the search_dir looks like an explicit filename (i.e. not a folder name)
        # by seeing if there is a '.' character in the last 6 characters of the name.  If it looks
        # like a file we'll try to download it diretly, bypassing any fzf handling.  If you have
        # file without an extension you can provide '-f' on the command line to force this, or
        # let fzf fail and then attempt to downloading the file.
        remote_file=${search_dir}
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
        if ${sort}; then sort_cmd="sort -n -r"; fi

        local find_cmd
        local shell_cmd
        local formatter="%TY-%Tm-%Td %Tl:%TM%Tp  %12s %p\n"

        local host_alias

        local host=${search_host}
        if ${is_local}; then
            host=$(hostname)
        else
            # resolve any alias to the real hostname
            host_alias=${host}
            host=$(ssh -G ${host} | awk '$1 == "hostname" { print $2 }')
            if ! [ "${host}" == "${host_alias}" ]; then
                host="${host_alias} => ${host}"
            fi
        fi

        fzf_params="--exit-0 --header=\"(${host}) Searching: ${search_dir}\""

        local filter_param
        if ${filter_hidden}; then
            if ${is_local}; then filter_param="! -path \"*/.*\""; else filter_param="! -path \\\"*/.*\\\""; fi
        fi

        local fzf_command="fzf +s +m --query=${query_str} ${fzf_params}"
        if ${is_local}; then
            find_cmd="find . -maxdepth ${maxdepth} -type f ${filter_param} -printf \"${formatter}\" 2> /dev/null"
            shell_cmd="pushd ${search_dir} >/dev/null && ${find_cmd} | ${sort_cmd} | ${fzf_command} && popd >/dev/null"
        else 
            find_cmd="find . -maxdepth ${maxdepth} -type f ${filter_param} -printf \\\"${formatter}\\\" 2> /dev/null"
            shell_cmd="ssh ${search_host} \"cd ${search_dir} && ${find_cmd} | ${sort_cmd}\" | ${fzf_command}"
        fi

        #echo ${shell_cmd} && return

        dir=$(eval ${shell_cmd})
        if [ $? -eq 130 ]; then
            return
        fi

        if [ "${dir}" == "" ]; then
            echo "checking to see if it is a file..."
            if ${is_local}; then
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
            # The last field in the find output is the filename
            local tokens=( $dir ) 
            remote_file=${search_dir}/${tokens[-1]}
        fi
    fi

    local same_file=false

    local copy_cmd="scp ${search_host}:${remote_file} ."
    if ${is_local}; then
        # Check to see if the selected file is present in the same folder.
        if [ "$(stat -L -c %d:%i ${remote_file})" = "$(stat -L -c %d:%i ./$(basename ${remote_file}) 2> /dev/null)" ]; then
            copy_cmd=""
            same_file=true
        else
            copy_cmd="cp ${remote_file} ."
             echo "Copying ${remote_file} to here..."
        fi
    else
        echo "Downloading: ${search_host}:${remote_file}..."
    fi

    eval ${copy_cmd}

    # If the fetch failed, remove any partial download/copy and exit.
    if [ $? -ne 0 ]; then
        if [ -f ./$(basename ${remote_file}) ]; then
            rm ./$(basename ${remote_file})
        fi
        return
    fi

    local local_file="$(basename ${remote_file})"
    
    local extracted=false

    if ${extract}; then
        if ${askExtract}; then
            while true; do

            read -p "Do you want to extract this asset here? (y/n) " yn

            case $yn in 
                [yY] )
                    break;;
                [nN] )
                    return;;
                * ) echo invalid response;;
            esac

            done            
        fi

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

            if [[ ${local_file} = ${ex[0]} ]]; then

                local cmdtokens=(${ex[1]})
                if ! [ -x "$(command -v ${cmdtokens[0]})" ]; then
                    echo "\"${cmdtokens[0]}\" not found.  Please install it, if needed, and"
                    echo "ensure it is on your path."
                    return
                fi

                # Do the extraction!
                echo "Extracting ${local_file}..."
                eval ${ex[1]} ${local_file} && extracted=true
                break
            fi
        done

        if ${extracted} && ${delete}; then
            if $same_file; then
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