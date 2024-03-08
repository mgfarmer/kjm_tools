#NoEnv  ; Recommended for performance and compatibility with future AutoHotkey releases.
; #Warn  ; Enable warnings to assist with detecting common errors.
SendMode Input  ; Recommended for new scripts due to its superior speed and reliability.
SetWorkingDir %A_ScriptDir%  ; Ensures a consistent starting directory.

#SingleInstance Force

FileCreateShortcut, %A_ScriptFullPath%, %A_Startup%\default_ahk.lnk
SetTitleMatchMode, 2
SetCapsLockState, alwaysoff

; Cycle: Windows --> RDP --> Linux --> Windows
#if !WinActive("system76-pc.local") and !WinActive("192.168.1.11")
  ^CapsLock::
    if (WinExist("system76-pc.local")) {
      Sleep 50
      ;WinActivate, "system76-pc.local"
      WinActivate  ahk_class TscShellContainerClass, 192.168.1.11
    }
  return
#if

; Remote Desktop Connection
;#if WinActive("ahk_class TscShellContainerClass")
#if WinActive("192.168.1.11")
  ^CapsLock::           ; Ctrl+Caps Lock (couldn't make Ctrl+Shift+Caps Lock work for some reason
    ; Need a short sleep here for focus to restore properly.
    Sleep 50
    WinMinimize A    ; need A to specify Active window
    if (WinExist("system76-pc.local")) {
      WinActivate ahk_class TscShellContainerClass, system76
    }
    ;MsgBox, Received Remote Desktop minimize hotkey    ; uncomment for debugging
  return
#if

;
;system76-pc.local - Remote Desktop Connection
; Remote Desktop Connection
;#if WinActive("ahk_class TscShellContainerClass")
#if WinActive("system76-pc.local")
  ^CapsLock::           ; Ctrl+Caps Lock (couldn't make Ctrl+Shift+Caps Lock work for some reason
    ; Need a short sleep here for focus to restore properly.
    Sleep 50
    WinMinimize A    ; need A to specify Active window
    ;MsgBox, Received Remote Desktop minimize hotkey    ; uncomment for debugging
  return
#if

; NoMachine System76-PC
;#if WinActive("ahk_exe nxplayer.bin")
;#if WinActive("NoMachine - System76-PC")
;  ^CapsLock::           ; Ctrl+Caps Lock (couldn't make Ctrl+Shift+Caps Lock work for some reason
;    ; Need a short sleep here for focus to restore properly.
;    Sleep 50
;    WinMinimize A    ; need A to specify Active window
;    ;MsgBox, Minimize NoMachine    ; uncomment for debugging
;  return
;#if

