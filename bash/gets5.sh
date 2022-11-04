gets5() {

    # Declare an array of handy shortcuts. The key can be provided
    # on the command line as the <remote_dir> and the full path
    # will be substituted.  Add as many as you want.
    declare -A loc_keys
    loc_keys["compiler"]="/nfs/teams/sw/share/compiler/releases/"
    loc_keys["ip"]="/nfs/teams/ret/share/release/"
    loc_keys["fs"]="/nfs/teams/sw/static/dev-tools/freedom-studio/"
    loc_keys["ft"]="/nfs/teams/sw/static/dev-tools/freedom-tools/"
    loc_keys["cxdoc"]="/nfs/teams/cx/share/documentation/"
    loc_keys["fusdk"]="/nfs/teams/sw/share/fusdk/"
    loc_keys["alg"]="/nfs/teams/sw/share/lib/"
    loc_keys["octane"]="/nfs/teams/sw/share/octane/"

    function usage() {
        echo "Find and download files on SiFive network machines."
        echo "Usage:"
        echo "  gets5 [-eEs] [-m maxdepth] [<remote_host>] <remote_dir>"
        echo ""
        echo "-e : extract the package if it is a recognized archive"
        echo "-E : like -e, but delete the archive after extraction"
        echo "-s : Usually entries are sorted by last mode date. This"
        echo "     flags turns off sorting by date."
        echo ""
        echo "-m maxdepth : Default is 6, so only files up to six levels"
        echo "   deep are shown.  This is primarily for speed.  You can"
        echo "   specify deeper, or shallower, if you want."
        echo ""
        echo "<remote_host> is the remote machine to search on. If <remote_host>"
        echo "is not specified \"${remote_host}\" will be used. You can change the"
        echo "default by editing this bash function.  This can also match a host"
        echo "entry in your .ssh/config file (which makes things easy)"
        echo ""
        echo "<remote_dir> is the root directory to search from."
        echo ""
        echo "The following shortcut keywords are configured:"
        echo ""
        for key in ${!loc_keys[@]}; do
            printf "  %-8s => %s\n" ${key} ${loc_keys[${key}]}
        done
        echo ""
        echo "Add or remove shortcuts by editing this script"
        echo ""

        return
    }

    local extract=0
    local delete=0
    local sort=1
    local maxdepth=6

    local OPTIND o
    while getopts "eEsm:" o; do
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
    # this example.)
    local remote_host=remote

    # Check that fzf is available
    if ! command -v fzf &> /dev/null
    then
        echo "This script requires 'fzf' to work but 'fzf'"
        echo "could not be found. Please install it and put"
        echo "it on the path."
        return
    fi

    local remote_dir
    if [ "$#" -eq 1 ]; then
        remote_dir=${1}
    elif [ "$#" -eq 2 ]; then
        remote_host=${1}
        remote_dir=${2}
    else
        usage
        return
    fi

    # If a shortcut was provided, find and substitute the full path.
    for key in ${!loc_keys[@]}; do
        if [ ${remote_dir} == ${key} ]; then
            remote_dir=${loc_keys[${key}]}
            break
        fi
    done

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
    
    if [ ${sort} -eq 1 ]; then
        dir=$(ssh ${remote_host} "cd ${remote_dir} && find . -maxdepth ${maxdepth} -type f \
        ! -path \"*/.*\" \
        -printf \"%TY-%Tm-%Td %Tl:%TM%Tp  %12s %p\n\" 2> /dev/null" | sort -n -r | fzf +s +m) 
    else
        dir=$(ssh ${remote_host} "cd ${remote_dir} && find . -maxdepth ${maxdepth} -type f \
        ! -path \"*/.*\" \
        -printf \"%TY-%Tm-%Td %Tl:%TM%Tp  %12s %p\n\" 2> /dev/null" | fzf +s +m) 
    fi
    
    if [ "${dir}" == "" ]; then
        # Nothing selected, op aborted!
        return
    fi

    # Third field in the find output is the filename
    local tokens=( $dir ) 
    local remote_file=${remote_dir}/${tokens[3]}

    scp ${remote_host}:${remote_file} .
    if [ $? -ne 0 ]; then
        echo "Oops, something went wrong during download..."
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
            echo "Removing ${local_file}"
            rm ${local_file}
        fi
    fi

    return
}