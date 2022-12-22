# Handy Tools by KJM

## TL;DR
- **bash/bash_aliases**: Useful bash aliases
- **fzf/fzftools.sh**: Useful fzf bash functions
- **gff/***: A tool for finding and downloading files from the intranet

Install all of these tools into your environment by:

Cloning this repo to your your system:

```git clone git@github.com:sifive/kjm_tools.git```

(obviously you need to adjust the paths below to match where you cloned this repo)

Then add this:

```source ~/git/kjm_tools/kjm_tools.sh```

at the end of your ~/.bashrc, then

```cp ~/git/kjm_tools/gff_config ~/.gff_config```

This is the gff configuration file.  Take a look at it.  The default settings
are fine, but you may need to edit some of the location shortcuts that have
local system paths so that those paths map to your system.

Next, read the Dependencies section below.  __It contains important information.__

Finally, read the READMEs in each subfolder to understand what you just installed and what fursther configuration or customization is available.

Lastly, log out, and back in to get these tools installed.

## Dependencies

### ssh

**gff** depends on being able to connect to remote servers so you need to ensure your 
environment is configured to easily connect to any remote machines that you might
want to search.  The easiest way to do this is to setup an alias in your ~/.ssh/config 
file, especially if tunnels are involved.  For instance, all network shares can be accessed 
via the login servers, so create a `gff_host` entry like this:

```
Host gff_host remote
  HostName login.sifive.com
  User kevinm
  IdentityFile ~/.ssh/id_rsa_s5
```

Note that `gff_host` is the default name that gff will use.  If you stick to this name no further ssh/gff configuration is required to get things working.

To ensure all is working, you should be able to:

```> ssh gff_host```

and be immediately logged into the host server.  If not, you got some fixin' to do.

### fzf (and others)

Several of these tools depend on the **fzf** tool. It needs to be installed
on your system.  This is usually done by:

Linux: ```sudo apt install fzf```

MacOS: ```brew install fzf coreutils```

Or equivalent for your chosen Linux flavor of the month.

