if ($host.Name -eq 'ConsoleHost') {
    Remove-Item alias:\where -Force
    Set-Alias -Name which -Value where
    
    oh-my-posh init pwsh --config https://raw.githubusercontent.com/mgfarmer/kjm_tools/main/powershell/oh-my-posh/agnoster.json | Invoke-Expression
    Import-Module posh-git
    $env:POSH_GIT_ENABLED = $true

    Import-Module PSReadLine
    #Set-PSReadLineKeyHandler -Key UpArrow -Function HistorySearchBackward
    #Set-PSReadLineKeyHandler -Key DownArrow -Function HistorySearchForward

    Set-PSReadLineKeyHandler -Key F7 `
        -BriefDescription History `
        -LongDescription 'Show command history' `
        -ScriptBlock {
        $pattern = $null
        [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$pattern, [ref]$null)
        if ($pattern) {
            $pattern = [regex]::Escape($pattern)
        }

        $history = [System.Collections.ArrayList]@(
            $last = ''
            $lines = ''
            foreach ($line in [System.IO.File]::ReadLines((Get-PSReadLineOption).HistorySavePath)) {
                if ($line.EndsWith('`')) {
                    $line = $line.Substring(0, $line.Length - 1)
                    $lines = if ($lines) {
                        "$lines`n$line"
                    }
                    else {
                        $line
                    }
                    continue
                }

                if ($lines) {
                    $line = "$lines`n$line"
                    $lines = ''
                }

                if (($line -cne $last) -and (!$pattern -or ($line -match $pattern))) {
                    $last = $line
                    $line
                }
            }
        )
        $history.Reverse()

        $command = $history | Out-GridView -Title History -PassThru
        if ($command) {
            [Microsoft.PowerShell.PSConsoleReadLine]::RevertLine()
            [Microsoft.PowerShell.PSConsoleReadLine]::Insert(($command -join "`n"))
        }
    }
}

# function _prompt {
#     $p = Split-Path -leaf -path (Get-Location)
#     "$p> "
# }

# function prompt {
#     # Your non-prompt logic here
#     $prompt = '' #Write-Prompt ($(if ($IsAdmin) { 'Elevated ' } else { '' })) -BackgroundColor DarkRed -ForegroundColor White -NoNewline
#     $prompt += & $GitPromptScriptBlock
#     #$prompt += Write-Prompt "Text after posh-git prompt" -ForegroundColor ([ConsoleColor]::Magenta)
#     if ($prompt) { "$prompt " } else { " " }
# }

# function _prompt {

#     #Assign Windows Title Text
#     $host.ui.RawUI.WindowTitle = "@ $pwd"

#     #Configure current user, current folder and date outputs
#     $CmdPromptCurrentFolder = Split-Path -Path $pwd -Leaf
#     $CmdPromptUser = [Security.Principal.WindowsIdentity]::GetCurrent();
#     $Date = Get-Date -Format 'dddd hh:mm:ss tt'

#     # Test for Admin / Elevated
#     $IsAdmin = (New-Object Security.Principal.WindowsPrincipal ([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)

#     #Calculate execution time of last cmd and convert to milliseconds, seconds or minutes
#     $LastCommand = Get-History -Count 1
#     if ($lastCommand) { $RunTime = ($lastCommand.EndExecutionTime - $lastCommand.StartExecutionTime).TotalSeconds }

#     if ($RunTime -ge 60) {
#         $ts = [timespan]::fromseconds($RunTime)
#         $min, $sec = ($ts.ToString("mm\:ss")).Split(":")
#         $ElapsedTime = -join ($min, " min ", $sec, " sec")
#     }
#     else {
#         $ElapsedTime = [math]::Round(($RunTime), 2)
#         $ElapsedTime = -join (($ElapsedTime.ToString()), " sec")
#     }

#     #Decorate the CMD Prompt
#     Write-Host ""
#     Write-host ($(if ($IsAdmin) { 'Elevated ' } else { '' })) -BackgroundColor DarkRed -ForegroundColor White -NoNewline
#     Write-Host " USER:$($CmdPromptUser.Name.split("\")[1]) " -BackgroundColor DarkBlue -ForegroundColor White -NoNewline
#     If ($CmdPromptCurrentFolder -like "*:*")
#     { Write-Host " $CmdPromptCurrentFolder "  -ForegroundColor White -BackgroundColor DarkGray -NoNewline }
#     else { Write-Host ".\$CmdPromptCurrentFolder\ "  -ForegroundColor White -BackgroundColor DarkGray -NoNewline }

#     Write-Host " $date " -ForegroundColor White
#     Write-Host "[$elapsedTime] " -NoNewline -ForegroundColor Green
#     return "> "
# } #end prompt function