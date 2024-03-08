#NoEnv  ; Recommended for performance and compatibility with future AutoHotkey releases.
; #Warn  ; Enable warnings to assist with detecting common errors.
SendMode Input  ; Recommended for new scripts due to its superior speed and reliability.
SetWorkingDir %A_ScriptDir%  ; Ensures a consistent starting directory.

#SingleInstance Force

FileCreateShortcut, %A_ScriptFullPath%, %A_Startup%\default_ahk.lnk
SetTitleMatchMode, 2
SetCapsLockState, alwaysoff

SYS76 := "system76-pc.local"
LAPTOP := "kmills-xps15.local"

; Cycle: Windows --> RDP --> Linux --> Windows
#if !WinActive(SYS76) and !WinActive(LAPTOP)
  ^CapsLock::
    Sleep 50
    if (WinExist(SYS76)) {
      WinActivate  ahk_class TscShellContainerClass, kmills-xps15
    }
  return
#if

#if WinActive(LAPTOP)
  ^CapsLock::
    ; Need a short sleep here for focus to restore properly.
    Sleep 50
    WinMinimize A    ; need A to specify Active window
    if (WinExist(SYS76)) {
      WinActivate ahk_class TscShellContainerClass, system76
    }
  return
#if

#if WinActive(SYS76)
  ^CapsLock::
    ; Need a short sleep here for focus to restore properly.
    Sleep 50
    WinMinimize A    ; need A to specify Active window
  return
#if
