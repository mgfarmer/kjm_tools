gff() {

    # Declare an array of handy shortcuts. The key can be provided
    # on the command line as the <search_dir> and the full path
    # will be substituted.  Add as many as you want.
    declare -A loc_keys
    loc_keys["compiler"]="/nfs/teams/sw/share/compiler/releases/"
    loc_keys["ip"]="/nfs/teams/ret/share/release/"
    loc_keys["fs"]="/nfs/teams/sw/static/dev-tools/freedom-studio/"
    loc_keys["fsorca"]="/nfs/teams/sw/static/dev-tools/freedom-studio/orca/sifive-internal"
    loc_keys["ft"]="/nfs/teams/sw/static/dev-tools/freedom-tools/"
    loc_keys["cxdoc"]="/nfs/teams/cx/share/documentation/"
    loc_keys["fusdk"]="/nfs/teams/sw/share/fusdk/"
    loc_keys["alg"]="/nfs/teams/sw/share/lib/"
    loc_keys["octane"]="/nfs/teams/sw/share/octane/"

    function usage() {
cat << EndOfUsage        
A fuzzy file finder for remote(ssh) and local folders.

Usage: gff [-reEsh] [-m maxdepth] [-q querystring] [-r <search_host>] <search_dir>

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
     Use this is the filesystem does not exist on the default
     remote host (for instance '/scratch' ).  You can change the default 
     remote host by editing this bash function. This can be a host entry 
     in your .ssh/config file (which makes things easy)

<search_dir> is the root directory to search from.

If the <search_dir> exists on the local system (where you are using
this script) then a local search will be done.  If you really want
to a remote search using the same <search_dir> then use the '-r'
flag to force a remote search.

Shortcuts are easy to remember keys for common search paths that
you use.  Add or remove shortcuts by editing this script.  It's easy.

The following shortcut keywords are currently configured:

EndOfUsage

        for key in ${!loc_keys[@]}; do
            printf "  %-8s => %s\n" ${key} ${loc_keys[${key}]}
        done
        return
    }

    local extract=0
    local delete=0
    local sort=1
    local maxdepth=6
    local force_remote=0
    local query_str=".tar.gz"

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
                query_str="${OPTARG}"
                ;;
            h)
                search_host="${OPTARG}"
                ;;
            *)
                usage
                ;;
        esac
    done
    shift $((OPTIND-1))

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

    local search_dir

    if [ "$#" -ne 1 ]; then
        echo "Too many paths...expecting only one"
        usage
        return
    fi

    local search_dir=${1}

    local is_local=0

    if [ ${search_host} == $(hostname) ]; then is_local=1; fi

    # If a shortcut was provided, find and substitute the full path.
    for key in ${!loc_keys[@]}; do
        if [ ${search_dir} == ${key} ]; then
            search_dir=${loc_keys[${key}]}
            break
        fi
    done

    if [ -d ${search_dir} ] && [ ${force_remote} -eq 0 ]; then is_local=1; fi

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

    local dir
    
    quote () { 
        local quoted=${1//\'/\'\\\'\'};
        printf "'%s'" "$quoted"
    }

    local sort_cmd="tee"
    if [ ${sort} -eq 1 ]; then sort_cmd="sort -n -r"; fi

    local find_cmd
    local shell_cmd
    local formatter="%TY-%Tm-%Td %Tl:%TM%Tp  %12s %p\n"

    local host=${search_host}
    if [ ${is_local} -eq 1 ]; then
        host=$(hostname)
    fi

    fzf_params="--header=\"(${host}) Searching: ${search_dir}\""

    if [ ${is_local} -eq 1 ]; then
        find_cmd="find . -maxdepth ${maxdepth} -type f ! -path \"*/.*\" -printf \"${formatter}\" 2> /dev/null"
        shell_cmd="pushd ${search_dir} >/dev/null && ${find_cmd} | ${sort_cmd} | fzf +s +m --query=${query_str} ${fzf_params} && popd >/dev/null"
    else 
        find_cmd="find . -maxdepth ${maxdepth} -type f ! -path \\\"*/.*\\\" -printf \\\"${formatter}\\\" 2> /dev/null"
        shell_cmd="ssh ${search_host} \"cd ${search_dir} && ${find_cmd} | ${sort_cmd}\" | fzf +s +m --query=${query_str} ${fzf_params}"
    fi

    dir=$(eval ${shell_cmd})
    
    if [ "${dir}" == "" ]; then
        # Nothing selected, op aborted!
        return
    fi

    # Third field in the find output is the filename
    local tokens=( $dir ) 
    local remote_file=${search_dir}/${tokens[3]}
    local same_file=0

    local copy_cmd="scp ${search_host}:${remote_file} ."
    if [ ${is_local} -eq 1 ]; then
        # Check to see if the selected file is present in the same folder.
        if [ "$(stat -L -c %d:%i ${remote_file})" = "$(stat -L -c %d:%i ./$(basename ${remote_file}) 2> /dev/null)" ]; then
            copy_cmd=""
            same_file=1
        else
            copy_cmd="cp ${remote_file} ."
        fi
    fi

    eval ${copy_cmd}

    if [ $? -ne 0 ]; then
        echo "Oops, something went wrong during download...ABORT!"
        return
    fi

    local local_file="$(basename ${remote_file})"
    
    

    local extracted=0
    if [ ${extract} -eq 1 ]; then
        echo "Extracting ${local_file}..."
        case "${local_file}" in
        *.tgz | *.tar.gz )
            tar xzf ${local_file}
            extracted=1
            ;;
        *.tar )
            tar xf ${local_file}
            extracted=1
            ;;
        *.gz | *.gzip )
            gunzip ${local_file}
            ;;
        *.zip )
            unzip ${local_file}
            extracted=1
            ;;
        * )
            echo "Oops: ${local_file} is not a recognized archive."
            echo "Only .tar.gz, .tgz, .tar, .gz, and .zip are known."
            ;;
        esac

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