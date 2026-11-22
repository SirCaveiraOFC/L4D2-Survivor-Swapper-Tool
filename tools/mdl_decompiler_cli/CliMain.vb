Imports System
Imports System.ComponentModel
Imports System.Globalization
Imports System.IO
Imports System.Threading

Namespace My
    Friend Module MyResourcesShim
        Friend Class ResourcesClass
            Public ReadOnly Property Decompile_LogFileNameSuffix As String
                Get
                    Return "decompile-log.txt"
                End Get
            End Property

            Public ReadOnly Property Decompile_DebugAniFileNameSuffix As String
                Get
                    Return "decompile-ANI.txt"
                End Get
            End Property

            Public ReadOnly Property Decompile_DebugMdlFileNameSuffix As String
                Get
                    Return "decompile-MDL.txt"
                End Get
            End Property

            Public ReadOnly Property Decompile_DebugPhyFileNameSuffix As String
                Get
                    Return "decompile-PHY.txt"
                End Get
            End Property

            Public ReadOnly Property Decompile_DebugSequenceGroupMDLFileNameSuffix As String
                Get
                    Return "decompile-SequenceGroupMDL.txt"
                End Get
            End Property

            Public ReadOnly Property Decompile_DebugTextureMDLFileNameSuffix As String
                Get
                    Return "decompile-TextureMDL.txt"
                End Get
            End Property

            Public ReadOnly Property Decompile_DebugVtxFileNameSuffix As String
                Get
                    Return "decompile-VTX.txt"
                End Get
            End Property

            Public ReadOnly Property Decompile_DebugVvdFileNameSuffix As String
                Get
                    Return "decompile-VVD.txt"
                End Get
            End Property
        End Class

        Friend ReadOnly Resources As New ResourcesClass()
    End Module
End Namespace

Public Class AppSettings
    Public Property DecompileMdlPathFileName As String = ""
    Public Property DecompileOutputFolderOption As DecompileOutputPathOptions = DecompileOutputPathOptions.WorkFolder
    Public Property DecompileOutputSubfolderName As String = "decompiled 0.74"
    Public Property DecompileOutputFullPath As String = ""

    Public Property DecompileQcFileIsChecked As Boolean = True
    Public Property DecompileGroupIntoQciFilesIsChecked As Boolean = False
    Public Property DecompileQcSkinFamilyOnSingleLineIsChecked As Boolean = True
    Public Property DecompileQcOnlyChangedMaterialsInTextureGroupLinesIsChecked As Boolean = True
    Public Property DecompileQcIncludeDefineBoneLinesIsChecked As Boolean = True
    Public Property DecompileQcUseMixedCaseForKeywordsIsChecked As Boolean = False

    Public Property DecompileReferenceMeshSmdFileIsChecked As Boolean = True
    Public Property DecompileRemovePathFromSmdMaterialFileNamesIsChecked As Boolean = True
    Public Property DecompileUseNonValveUvConversionIsChecked As Boolean = False

    Public Property DecompileTextureBmpFilesIsChecked As Boolean = True
    Public Property DecompileLodMeshSmdFilesIsChecked As Boolean = True
    Public Property DecompilePhysicsMeshSmdFileIsChecked As Boolean = True
    Public Property DecompileVertexAnimationVtaFileIsChecked As Boolean = True
    Public Property DecompileProceduralBonesVrdFileIsChecked As Boolean = True
    Public Property DecompileBoneAnimationSmdFilesIsChecked As Boolean = True
    Public Property DecompileBoneAnimationPlaceInSubfolderIsChecked As Boolean = True

    Public Property DecompileFolderForEachModelIsChecked As Boolean = False
    Public Property DecompilePrefixFileNamesWithModelNameIsChecked As Boolean = False
    Public Property DecompileStricterFormatIsChecked As Boolean = False
    Public Property DecompileLogFileIsChecked As Boolean = False
    Public Property DecompileDebugInfoFilesIsChecked As Boolean = False
    Public Property DecompileDeclareSequenceQciFileIsChecked As Boolean = False
    Public Property DecompileOverrideMdlVersion As SupportedMdlVersion = SupportedMdlVersion.DoNotOverride
    Public Property DecompileMode As InputOptions = InputOptions.File
    Public Property DecompilerIsRunning As Boolean = False
End Class

Public Class App
    Public Const AnimsSubFolderName As String = "anims"

    Private ReadOnly theInternalCultureInfo As CultureInfo
    Private ReadOnly theInternalNumberFormat As NumberFormatInfo
    Private ReadOnly theSettings As AppSettings
    Private theSmdFilesWritten As List(Of String)

    Public Sub New()
        Me.theInternalCultureInfo = New CultureInfo("en-US", False)
        Me.theInternalNumberFormat = Me.theInternalCultureInfo.NumberFormat
        Me.theSettings = New AppSettings()
        Me.theSmdFilesWritten = New List(Of String)()
    End Sub

    Public ReadOnly Property Settings As AppSettings
        Get
            Return Me.theSettings
        End Get
    End Property

    Public ReadOnly Property InternalCultureInfo As CultureInfo
        Get
            Return Me.theInternalCultureInfo
        End Get
    End Property

    Public ReadOnly Property InternalNumberFormat As NumberFormatInfo
        Get
            Return Me.theInternalNumberFormat
        End Get
    End Property

    Public Property SmdFileNames As List(Of String)
        Get
            Return Me.theSmdFilesWritten
        End Get
        Set(value As List(Of String))
            Me.theSmdFilesWritten = value
        End Set
    End Property

    Public Function GetDebugPath(ByVal outputPath As String, ByVal modelName As String) As String
        Return outputPath
    End Function

    Public Function GetHeaderComment() As String
        Return "Created by " & Me.GetProductNameAndVersion()
    End Function

    Public Function GetProductNameAndVersion() As String
        Return "Crowbar 0.74"
    End Function
End Class

Public Module Main
    Public TheApp As App

    Public Function Main(ByVal args() As String) As Integer
        Dim inputPath As String = ""
        Dim outputDir As String = ""
        Dim includeDefineBones As Boolean = True

        Dim i As Integer = 0
        While i < args.Length
            Dim arg As String = args(i)
            If (arg = "--input" OrElse arg = "-i") AndAlso i + 1 < args.Length Then
                i += 1
                inputPath = args(i)
            ElseIf (arg = "--output" OrElse arg = "-o") AndAlso i + 1 < args.Length Then
                i += 1
                outputDir = args(i)
            ElseIf arg = "--no-define-bones" Then
                includeDefineBones = False
            ElseIf arg = "--help" OrElse arg = "-h" Then
                Console.WriteLine("MdlDecompilerCli - Headless Source MDL Decompiler (based on Crowbar 0.74 by ZeqMacaw)")
                Console.WriteLine("Usage: MdlDecompilerCli.exe --input <model.mdl> --output <output_dir> [--no-define-bones]")
                Return 0
            End If
            i += 1
        End While

        If String.IsNullOrEmpty(inputPath) OrElse Not File.Exists(inputPath) Then
            Console.Error.WriteLine("ERROR: Input MDL file not found: " & inputPath)
            Return 2
        End If

        If String.IsNullOrEmpty(outputDir) Then
            outputDir = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(inputPath)), "decompiled 0.74")
        End If

        TheApp = New App()
        TheApp.Settings.DecompileMode = InputOptions.File
        TheApp.Settings.DecompileMdlPathFileName = Path.GetFullPath(inputPath)
        TheApp.Settings.DecompileOutputFolderOption = DecompileOutputPathOptions.WorkFolder
        TheApp.Settings.DecompileOutputFullPath = Path.GetFullPath(outputDir)
        TheApp.Settings.DecompileQcIncludeDefineBoneLinesIsChecked = includeDefineBones

        Dim decompiler As New Decompiler()
        Dim done As New ManualResetEvent(False)
        Dim finalStatus As StatusMessage = StatusMessage.[Error]

        AddHandler decompiler.ProgressChanged, Sub(sender As Object, e As ProgressChangedEventArgs)
            Dim line As String = TryCast(e.UserState, String)
            If line IsNot Nothing AndAlso line.Length > 0 Then
                Console.WriteLine(line.TrimStart(ControlChars.Cr))
            End If
        End Sub

        AddHandler decompiler.RunWorkerCompleted, Sub(sender As Object, e As RunWorkerCompletedEventArgs)
            If e.Error IsNot Nothing Then
                Console.Error.WriteLine("ERROR: " & e.Error.ToString())
                finalStatus = StatusMessage.[Error]
            ElseIf e.Cancelled Then
                finalStatus = StatusMessage.Canceled
            Else
                Dim outInfo As DecompilerOutputInfo = TryCast(e.Result, DecompilerOutputInfo)
                If outInfo IsNot Nothing Then
                    finalStatus = outInfo.theStatus
                End If
            End If
            done.Set()
        End Sub

        decompiler.Run()
        done.WaitOne()

        Dim expectedQc As String = Path.Combine(
            Path.GetFullPath(outputDir),
            Path.GetFileNameWithoutExtension(inputPath) & ".qc"
        )
        If finalStatus = StatusMessage.Success AndAlso File.Exists(expectedQc) Then
            Return 0
        Else
            Console.Error.WriteLine("Decompile failed with status: " & finalStatus.ToString())
            Return 1
        End If
    End Function
End Module
