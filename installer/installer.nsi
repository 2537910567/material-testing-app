; NSIS 安装脚本 — 工程材料送检分析系统 V6.1
; 编译: makensis installer\installer.nsi

!define APP_NAME "MaterialTestingTool"
!define APP_DISPLAY "工程材料送检分析系统"
!define APP_VERSION "6.1.0"
!define PUBLISHER "MaterialTestingTool"
!define OUTPUT_DIR "..\dist\MaterialTestingTool"

Name "${APP_DISPLAY}"
OutFile "${APP_NAME}-Setup-v${APP_VERSION}.exe"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
RequestExecutionLevel admin

SetCompressor /SOLID lzma
SetCompressorDictSize 64

; ── 界面 ──
!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ABORTWARNING
!define MUI_ICON "..\app_icon.png"
!define MUI_UNICON "..\app_icon.png"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "license.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

; ── 安装 ──
Section "Install"
    SetOutPath "$INSTDIR"

    ; 1. VC++ Redist 检测 + 安装
    ${If} ${FileExists} "$INSTDIR\vc_redist.x64.exe"
        DetailPrint "安装 VC++ Redist..."
        ExecWait '"$INSTDIR\vc_redist.x64.exe" /install /quiet /norestart' $0
        DetailPrint "VC++ Redist 完成 (exit=$0)"
    ${EndIf}

    ; 2. ODA File Converter 检测 + 安装
    ; ODAFC 安装包需放入 DIST 目录（ODAFC_Setup.exe）
    IfFileExists "$INSTDIR\ODAFC_Setup.exe" 0 skip_odafc
        DetailPrint "安装 ODA File Converter..."
        ExecWait '"$INSTDIR\ODAFC_Setup.exe" /SILENT' $0
        DetailPrint "ODAFC 完成 (exit=$0)"
    skip_odafc:

    ; 3. 复制应用程序文件
    DetailPrint "安装应用程序..."
    File /r "${OUTPUT_DIR}\*.*"

    ; 4. 快捷方式
    CreateDirectory "$SMPROGRAMS\${APP_DISPLAY}"
    CreateShortCut "$SMPROGRAMS\${APP_DISPLAY}\${APP_DISPLAY}.lnk" "$INSTDIR\MaterialTestingTool.exe"
    CreateShortCut "$DESKTOP\${APP_DISPLAY}.lnk" "$INSTDIR\MaterialTestingTool.exe"

    ; 5. 注册表（用于更新检测和卸载）
    WriteRegStr HKLM "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "Software\${APP_NAME}" "Version" "${APP_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "DisplayName" "${APP_DISPLAY}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "Publisher" "${PUBLISHER}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "NoRepair" 1
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" \
        "EstimatedSize" "$0"

    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

; ── 卸载 ──
Section "Uninstall"
    ; 删除程序文件
    RMDir /r "$INSTDIR\_internal"
    Delete "$INSTDIR\MaterialTestingTool.exe"
    Delete "$INSTDIR\uninstall.exe"
    Delete "$INSTDIR\*.dll"
    Delete "$INSTDIR\*.pyd"
    RMDir /r "$INSTDIR\qml"
    RMDir /r "$INSTDIR\database"
    RMDir "$INSTDIR"

    ; 删除快捷方式
    Delete "$SMPROGRAMS\${APP_DISPLAY}\${APP_DISPLAY}.lnk"
    RMDir "$SMPROGRAMS\${APP_DISPLAY}"
    Delete "$DESKTOP\${APP_DISPLAY}.lnk"

    ; 删除注册表
    DeleteRegKey HKLM "Software\${APP_NAME}"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

    ; 保留用户数据（不删除 ~\.material_testing_tool\）
    MessageBox MB_OK "用户数据已保留在 %USERPROFILE%\.material_testing_tool\ 目录。$\n如需彻底清除请手动删除。"
SectionEnd

; ── 升级检测函数 ──
Function .onInit
    ; 检测旧版本
    ReadRegStr $0 HKLM "Software\${APP_NAME}" "InstallDir"
    ${If} $0 != ""
        ReadRegStr $1 HKLM "Software\${APP_NAME}" "Version"
        ${If} $1 S< "${APP_VERSION}"
            MessageBox MB_YESNO "检测到已安装旧版本 $1。是否升级到 ${APP_VERSION}？$\n（升级将覆盖程序文件，保留用户数据）" IDYES upgrade
            Abort
            upgrade:
            StrCpy $INSTDIR $0  ; 使用旧安装路径
        ${EndIf}
    ${EndIf}
FunctionEnd
