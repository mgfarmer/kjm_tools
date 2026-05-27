# Handy Tools by KJM

## TL;DR

- **bash/bash_aliases**: Useful bash aliases
- **fzf/fzftools.sh**: Useful fzf bash functions

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

Next, read the Dependencies section below.  **It contains important information.**

Finally, read the READMEs in each subfolder to understand what you just installed and what fursther configuration or customization is available.

Lastly, log out, and back in to get these tools installed.

## Dependencies

### fzf (and others)

Several of these tools depend on the **fzf** tool. It needs to be installed
on your system.  This is usually done by:

Linux: ```sudo apt install fzf```

MacOS: ```brew install fzf coreutils```

Or equivalent for your chosen Linux flavor of the month.
