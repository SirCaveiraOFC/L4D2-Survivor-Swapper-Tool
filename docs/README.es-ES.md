# L4D2 Survivor Swapper Tool | v2.1.0

> 🌐 **Idioma:** [English](../README.md) | [Português (Brasil)](README.pt-BR.md) | **Español**  ·  📋 [Changelog](../CHANGELOG.md)

Herramienta automatizada e interfaz de escritorio Fluent UI para portar mods `.vpk` de supervivientes de **Left 4 Dead 2** entre cualquiera de los 8 personajes (`Bill`, `Zoey`, `Louis`, `Francis`, `Nick`, `Rochelle`, `Coach` y `Ellis`), con cola por lotes, descargas de Steam Workshop y actualizador integrado por GitHub.

---

## Índice

- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Guía Rápida y Funcionalidades](#guía-rápida-y-funcionalidades)
  - [1. Asistente Inicial (`Setup Wizard`)](#1-asistente-inicial-setup-wizard)
  - [2. Conversión Individual (`Individual`)](#2-conversión-individual-individual)
  - [3. Confirmación Previa](#3-confirmación-previa)
  - [4. Conversión por Lotes (`Por Lotes`)](#4-conversión-por-lotes-por-lotes)
  - [5. Mis Mods (`Mis Mods`)](#5-mis-mods-mis-mods)
  - [6. Descarga de Steam Workshop (`Descargar`)](#6-descarga-de-steam-workshop-descargar)
  - [7. Historial de Conversiones (`Historial`)](#7-historial-de-conversiones-historial)
  - [8. Diagnóstico del Entorno (`Entorno`)](#8-diagnóstico-del-entorno-entorno)
  - [9. Actualizador Integrado (`Actualizaciones`)](#9-actualizador-integrado-actualizaciones)
  - [10. Ajustes y Acerca de (`Ajustes`)](#10-ajustes-y-acerca-de-ajustes)
- [Etiquetas / Placeholders de Salida](#etiquetas--placeholders-de-salida)
- [Modo Línea de Comandos (CLI)](#modo-línea-de-comandos-cli)
- [Arquitectura del Proyecto](#arquitectura-del-proyecto)
- [Compartir una Copia Limpia](#compartir-una-copia-limpia)
- [Ejecutar Pruebas](#ejecutar-pruebas)
- [Contacto, Créditos y Licencia](#contacto-créditos-y-licencia)

---

## Requisitos

- **Windows 10 / 11** (`x64`)
- **Left 4 Dead 2** instalado mediante Steam (`AppID 550`)
- **Left 4 Dead 2 Authoring Tools** instalado desde Biblioteca de Steam → Herramientas (`AppID 563`, incluye `studiomdl.exe` y `vpk.exe`)
- **Python 3.10+** (se recomienda `3.13`) — **no es necesario** en la edición Portátil `.exe`; solo hace falta al ejecutar desde el código fuente ([`requirements.txt`](../requirements.txt): `PySide6>=6.9.0`, `PySide6-Fluent-Widgets>=1.11.0`, `vpk>=1.4.0`, `vdf>=3.4`, `psutil>=5.9.0`)

---

## Instalación

### Opción A — Edición Portátil `.exe` (Recomendado, Sin Python)

1. Descarga el `.zip` Portátil desde Releases (o créalo desde el código fuente con [`tools/build_portable.ps1`](../tools/build_portable.ps1)).
2. Extrae la carpeta en cualquier ubicación de tu PC (ej. `C:\L4D2-Survivor-Swapper-Tool\`).
3. Asegúrate de tener **Left 4 Dead 2** y **Left 4 Dead 2 Authoring Tools** instalados en Steam.
4. Haz doble clic en `L4D2 Survivor Swapper Tool.exe` para iniciar (incluye entorno Python integrado y soporte completo para el actualizador integrado de GitHub).

### Opción B — Desde Código Fuente (`.bat` en Windows o Terminal)

```powershell
git clone https://github.com/SirCaveiraOFC/L4D2-Survivor-Swapper-Tool.git
cd L4D2-Survivor-Swapper-Tool
pip install -r requirements.txt
python app.py
```

O haz doble clic en [`_INSTALL_REQUIREMENTS.bat`](../_INSTALL_REQUIREMENTS.bat) y luego en [`_RUN.bat`](../_RUN.bat) tras descargar o clonar el repositorio.

*(Para recompilar [`MdlDecompilerCli.exe`](../tools/mdl_decompiler_cli/MdlDecompilerCli.exe) desde el código fuente VB.NET de Crowbar, consulta [`build.ps1`](../tools/mdl_decompiler_cli/build.ps1) y [`NOTICE.txt`](../tools/mdl_decompiler_cli/NOTICE.txt). Para empaquetar una edición Portátil con `L4D2 Survivor Swapper Tool.exe`, ejecuta [`tools/build_portable.ps1`](../tools/build_portable.ps1).)*

---

## Guía Rápida y Funcionalidades

### 1. Asistente Inicial (`Setup Wizard`)

Al iniciar por primera vez (o si faltan rutas de Steam/Authoring Tools), el asistente detecta automáticamente Steam, Left 4 Dead 2 (`AppID 550`), `studiomdl.exe` + `vpk.exe` (`AppID 563`), `MdlDecompilerCli.exe`, y sincroniza `%APPDATA%\ZeqMacaw\Crowbar 0.74\Crowbar Settings.xml` con copia de seguridad `.bak`.

---

### 2. Conversión Individual (`Individual`)

1. Arrastra un archivo `.vpk`, `.zip` / `.rar` / `.7z` (con selector si contiene múltiples `.vpk`) o carpeta extraída al Paso 1 — o selecciona desde **Addons / Workshop de L4D2** o mediante un **Enlace de Workshop**.
2. Revisa el **Superviviente de Origen** detectado automáticamente, los recursos (`Cuerpo`, `Brazos`, `VGUI`, `Física`) y las texturas `.vtf` decodificadas (Lobby, HUD, Incapacitado — haz clic para ampliar).
3. Elige uno o varios supervivientes de destino agrupados en **L4D1** y **L4D2** (o usa los accesos rápidos `Todos los Demás`, `Grupo L4D1`, `Grupo L4D2`, `Limpiar`).
4. Personaliza las plantillas de archivo/título con etiquetas clicables, metadatos (`Autor`, `Versión`, `Descripción`), imagen de portada (`addonimage.jpg` / `.png`) y las **Opciones de Conversión** agrupadas (`Assets del Modelo` y `Salida y Metadatos`), y pulsa **Iniciar Conversión**.

---

### 3. Confirmación Previa

Antes de compilar, una ventana de resumen muestra la portada, archivo de origen, rutas (`Origen -> Destinos`), nombres finales de los `.vpk` y opciones activas (en cola por lotes puedes recorrer los mods con **Anterior** / **Siguiente** o las flechas `←` / `→`).

---

### 4. Conversión por Lotes (`Por Lotes`)

Agrega múltiples mods a la cola desde archivos, carpetas, Addons/Workshop locales o múltiples enlaces de Steam Workshop:
- Configura los **Valores Globales de la Cola** (destinos, plantillas y opciones) y aplícalos a todos con un clic.
- O desmarca **Usar Valores Globales** en cualquier mod para personalizar sus propios destinos, origen, portada y opciones.

---

### 5. Mis Mods (`Mis Mods`)

Gestiona los mods de supervivientes en `left4dead2/addons/` y `addons/workshop/`:
- 8 tarjetas clicables de personajes que muestran los mods activos y posibles conflictos.
- Filtra por búsqueda, carpeta (`addons` vs `workshop`), superviviente/generación y estado (`Activo` / `Desactivado`).
- Activa/desactiva entradas en `addonlist.txt`, amplía portadas, elimina `.vpk` o carga cualquier mod directamente en el conversor.

---

### 6. Descarga de Steam Workshop (`Descargar`)

Pega una o varias URLs/IDs de Steam Workshop para inspeccionar detalles y descargar archivos `.vpk` en `Workshop_Downloads/`:
- Muestra suscriptores, favoritos, visitantes, tamaño, calificación por estrellas, fechas, etiquetas y portada (compatible con GIF animados y zoom).
- Detecta mods que no son skins de supervivientes (`Script VScript`, `Campaña`, `Arma`, `Infectado`, `HUD`, `Audio`) permitiendo instalarlos en `addons/`.
- Administra tu biblioteca local en `Workshop_Downloads/` y envía skins directamente a **Individual**, **Por Lotes** o `addons/`.
- Haz clic en **Leer Descripción Completa** (o en la caja de resumen) para ver la descripción completa formateada desde Steam BBCode.

---

### 7. Historial de Conversiones (`Historial`)

Consulta conversiones pasadas, revisa cada archivo `.vpk` generado, reabre la fuente en el Swapper, abre la carpeta de salida o reinstala comprobando conflictos en `addons/`.

---

### 8. Diagnóstico del Entorno (`Entorno`)

Comprueba en vivo el estado de Left 4 Dead 2, Authoring Tools (`studiomdl.exe`, `vpk.exe`), `MdlDecompilerCli.exe` y `Crowbar Settings.xml`, vuelve a detectar rutas o abre el asistente de configuración.

---

### 9. Actualizador Integrado (`Actualizaciones`)

Mantén la aplicación actualizada desde GitHub sin perder ajustes ni mods:
- Comprueba automáticamente **GitHub Releases** o la rama configurada (`core/app_meta.py`).
- Muestra las notas de versión y una tabla exacta de archivos y carpetas modificadas (`+ Nuevo`, `~ Modificado`, `- Eliminado`) antes de instalar.
- Protege automáticamente tus datos (`settings.json`, `conversion_history.json`, `Swapped_Survivors/`, `Survivor_Swap/`, `Workshop_Downloads/`), crea copia de seguridad, actualiza dependencias si cambió `requirements.txt` y reinicia limpiamente al finalizar.

---

### 10. Ajustes y Acerca de (`Ajustes`)

Configura rutas manuales (`L4D2`, `studiomdl.exe`, `vpk.exe`, `Salida`, `Workshop_Downloads`, `Swap Kit`), preferencias (`Auto-Instalar`, `Modo Debug`), **Tema** (`Oscuro` por defecto, con `Sistema` / `Claro`), **Idioma** (`Auto` / `en-US` / `pt-BR` / `es-ES`) e información **Acerca de**.

---

## Etiquetas / Placeholders de Salida

Haz clic en las etiquetas o escríbelas en **Nombre de Archivo** y **Título del Addon**:

| Etiqueta | Reemplazada por | Ejemplo |
|---|---|---|
| `{survivor}` | Nombre del superviviente destino (minúscula en archivos) | `Nick` / `nick` |
| `{origin}` | Nombre del superviviente original del mod | `Zoey` / `zoey` |
| `{orig_title}` | Título original limpio (quita menciones redundantes al origen) | `Emma Frost` |
| `{title}` | Alias de `{orig_title}` | `Emma Frost` |
| `{generation}` | Generación destino (`L4D1` o `L4D2`) | `L4D2` |
| `{origin_generation}` | Generación origen (`L4D1` o `L4D2`) | `L4D1` |
| `{display_name}` | Nombre visible capitalizado del destino | `Nick` |
| `{survivor_id}` | Identificador interno del modelo Source | `survivor_gambler` |

---

## Modo Línea de Comandos (CLI)

Comprobar el entorno:

```powershell
python app.py --check-env
```

Sincronizar ajustes de Crowbar `0.74`:

```powershell
python app.py --apply-crowbar-settings --check-env
```

Convertir un `.vpk` a supervivientes específicos:

```powershell
python app.py --cli --source "Survivor_Swap\emma-zoey.vpk" --dest bill louis francis nick rochelle coach ellis --output-name "emma-{survivor}"
```

O portar a los otros 7 supervivientes e instalar en `addons/`:

```powershell
python app.py --cli --source "Survivor_Swap\emma-zoey.vpk" --all-except-origin --output-name "emma-{survivor}" --install
```

Opciones útiles: `--output-dir`, `--origin`, `--title`, `--author`, `--version`, `--description`, `--no-arms`, `--no-vgui`, `--no-weapons`, `--keep-temp`.

---

## Arquitectura del Proyecto

```text
.
├── app.py                              # Punto de entrada unificado (CLI y GUI)
├── _RUN.bat                            # Lanzador silencioso en Windows (vía pythonw)
├── _INSTALL_REQUIREMENTS.bat           # Instalador automático de requirements.txt
├── requirements.txt                    # Dependencias de Python
├── core/                               # Motor headless orientado a objetos
│   ├── addons_scanner.py               # Escáner de addons/workshop y gestor de addonlist.txt
│   ├── app_meta.py                     # Nombre, versión semántica, autor y datos de GitHub
│   ├── archive_service.py              # Validación y extracción segura de .zip/.rar/.7z
│   ├── config_manager.py               # Persistencia de settings.json y rutas
│   ├── crowbar_settings.py             # Validador/sincronizador XML de Crowbar 0.74 con .bak
│   ├── history_manager.py              # Persistencia de conversion_history.json
│   ├── i18n.py                         # Detección de idioma + traducciones en-US/pt-BR/es-ES
│   ├── mdl_toolchain.py                # Wrappers MdlDecompilerCli, studiomdl.exe y ejecución cancelable
│   ├── models.py                       # Dataclasses tipadas, enum SurvivorId y SwapCancelledError
│   ├── qc_merger.py                    # Fusionador universal AST de .qc (cuerpo y brazos)
│   ├── qc_parser.py                    # Parser .qc compatible con comillas, comentarios y llaves
│   ├── smd_splitter.py                 # Divisor automático de SMDs >20k triángulos para StudioMDL
│   ├── steam_bbcode.py                 # Conversor BBCode de Steam Workshop a HTML estilizado
│   ├── steam_locator.py                # Detector Steam/L4D2/Authoring Tools por Registro y VDF
│   ├── survivors.py                    # SurvivorRegistry (modelos, brazos FPS, ranuras VGUI, kits)
│   ├── swap_engine.py                  # Pipeline transaccional multi-destino y placeholders
│   ├── updater.py                      # Comprobador de releases/árbol GitHub, ZIP stager y aplicador
│   ├── vpk_service.py                  # Extracción segura de VPK (utf-8/latin-1), empaquetado y addoninfo
│   ├── vtf_decoder.py                  # Decodificador nativo de texturas .vtf para vistas VGUI
│   └── workshop_downloader.py          # Inspector API/HTML de Steam Workshop y descargador de VPK
├── ui/                                 # Interfaz gráfica PySide6 + PySide6-Fluent-Widgets
│   ├── addon_ui_shared.py              # Tablas, zoom, cierre seguro de QThread y paneles agrupados
│   ├── addons_browser_dialog.py        # Selector de addons/workshop y resolutor de conflictos
│   ├── addons_page.py                  # Pestaña Mis Mods (ranuras + gestor de addonlist.txt)
│   ├── batch_page.py                   # Pestaña Por Lotes con valores globales y por mod
│   ├── conversion_confirm_dialog.py    # Modal de confirmación previa a la conversión
│   ├── download_page.py                # Centro de descargas de Workshop y biblioteca local
│   ├── environment_page.py             # Tarjetas visuales de diagnóstico L4D2 / Tools / Crowbar
│   ├── error_dialog.py                 # Modal de errores desplazable con copia al portapapeles
│   ├── history_page.py                 # Historial con reinstalación y reapertura en 1 clic
│   ├── main_window.py                  # Ventana principal FluentWindow, navegación, tema e insignia Actualizaciones
│   ├── settings_page.py                # Rutas, apariencia, idioma y Acerca de
│   ├── setup_wizard.py                 # Asistente inicial automatizado
│   ├── swap_page.py                    # Conversión individual, VGUI, progreso y registros
│   ├── theme.py                        # Paleta L4D2 (Amarillo/Rojo/Negro/Blanco), hover y repintado
│   ├── updates_page.py                 # Pestaña Actualizaciones con changelog y tabla de archivos cambiados
│   ├── widgets.py                      # Banner, zona de arrastre, selector agrupado, zoom y etiquetas
│   ├── workshop_description_dialog.py  # Visor enriquecido de descripción BBCode de Steam
│   └── workshop_download_dialog.py     # Modal rápido de descarga por URL/ID de Workshop
├── docs/                               # Documentación localizada (PT-BR / ES-ES)
├── tools/
│   ├── launcher/                       # Launcher nativo .exe para Windows (C#) + script de compilación
│   ├── mdl_decompiler_cli/           # CLI headless Crowbar 0.74 en VB.NET + script de compilación
│   └── build_portable.ps1              # Empaquetador portátil con Python 3.13.5 integrado (.exe / .zip)
├── HUNK'S_SURVIVOR_SWAP_KIT/           # Plantillas base de QC/animaciones/rig por superviviente
├── legacy/                             # Scripts v1.x archivados y binario Crowbar.exe anterior
└── tests/                              # Pruebas unitarias y de interfaz headless (pytest)
```

---

## Compartir una Copia Limpia

Antes de comprimir la carpeta para distribuirla, elimina archivos locales personales para que el nuevo usuario reciba una configuración inicial limpia:

- Borra `settings.json`, `conversion_history.json` y `.update_manifest.json`.
- Vacía o excluye `Survivor_Swap/`, `Swapped_Survivors/`, `Workshop_Downloads/`, `.pytest_cache/`, `__pycache__/`, `dist/` y opcionalmente `legacy/`. (Conserva `runtime/` si compartes una edición Portátil; omite `runtime/` en copias solo de código fuente.)

---

## Ejecutar Pruebas

```powershell
pytest
```

---

## Contacto, Créditos y Licencia

- **Contacto** — Email: [srcaveiraoficial@gmail.com](mailto:srcaveiraoficial@gmail.com)
- **GitHub** — [SirCaveiraOFC/L4D2-Survivor-Swapper-Tool](https://github.com/SirCaveiraOFC/L4D2-Survivor-Swapper-Tool)
- **Sr.Caveira** — Creador, arquitectura y automatización de L4D2 Survivor Swapper Tool
- **ZeqMacaw** — Motor de descompilación [Crowbar](https://github.com/ZeqMacaw/Crowbar) (avisos de licencia en [`tools/mdl_decompiler_cli/NOTICE.txt`](../tools/mdl_decompiler_cli/NOTICE.txt))
- **H.U.N.K** — Plantillas base `.qc` de `HUNK'S_SURVIVOR_SWAP_KIT`
- **Valve Corporation** — Source Engine SDK (`studiomdl.exe`, `vpk.exe`)

Licenciado bajo **PolyForm Noncommercial 1.0.0** (libre para usar y modificar con fines no comerciales; se prohíbe su venta o uso comercial). Consulta [`LICENSE`](../LICENSE) y [`tools/mdl_decompiler_cli/NOTICE.txt`](../tools/mdl_decompiler_cli/NOTICE.txt) para detalles completos.
