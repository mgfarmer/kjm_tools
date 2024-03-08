#NoEnv  ; Recommended for performance and compatibility with future AutoHotkey releases.
; #Warn  ; Enable warnings to assist with detecting common errors.
SendMode Input  ; Recommended for new scripts due to its superior speed and reliability.
SetWorkingDir %A_ScriptDir%  ; Ensures a consistent starting directory.

#SingleInstance Force

FileCreateShortcut, %A_ScriptFullPath%, %A_Startup%\default_ahk.lnk
SetTitleMatchMode, 2
SetCapsLockState, alwaysoff

; Cycle: Windows --> RDP --> Linux --> Windows
#if !WinActive("ahk_class TscShellContainerClass") and !WinActive("ahk_exe nxplayer.bin")
  ^CapsLock::
    if (WinExist("ahk_class TscShellContainerClass")) {
      Sleep 50
      WinActivate, ahk_class TscShellContainerClass
    }
  return
#if

; Remote Desktop Connection
#if WinActive("ahk_class TscShellContainerClass")
  ^CapsLock::           ; Ctrl+Caps Lock (couldn't make Ctrl+Shift+Caps Lock work for some reason
    ; Need a short sleep here for focus to restore properly.
    Sleep 50
    WinMinimize A    ; need A to specify Active window
    if (WinExist("ahk_exe nxplayer.bin")) {
      Sleep 50
      WinActivate, ahk_exe nxplayer.bin
    }
    ;MsgBox, Received Remote Desktop minimize hotkey    ; uncomment for debugging
  return
#if

; NoMachine System76-PC
#if WinActive("ahk_exe nxplayer.bin")
  ^CapsLock::           ; Ctrl+Caps Lock (couldn't make Ctrl+Shift+Caps Lock work for some reason
    ; Need a short sleep here for focus to restore properly.
    Sleep 50
    WinMinimize A    ; need A to specify Active window
    ;MsgBox, Minimize NoMachine    ; uncomment for debugging
  return
#if

