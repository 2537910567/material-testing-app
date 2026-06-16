Unicode true
!include "MUI2.nsh"
Name "Test"
OutFile "test.exe"
InstallDir "$PROGRAMFILES64\Test"
RequestExecutionLevel admin
!insertmacro MUI_LANGUAGE "SimpChinese"
Section "Install"
    DetailPrint "Test OK"
SectionEnd
