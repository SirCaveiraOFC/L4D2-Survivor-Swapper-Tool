# L4D2 Survivor Swapper Tool | v2.0.1

> 🌐 **Idioma:** [English](../README.md) | **Português (Brasil)** | [Español](README.es-ES.md)

Toolchain automatizado e interface desktop moderna em Fluent UI para portar mods `.vpk` de sobreviventes do **Left 4 Dead 2** entre qualquer um dos 8 personagens (`Bill`, `Zoey`, `Louis`, `Francis`, `Nick`, `Rochelle`, `Coach` e `Ellis`), com fila em lote, downloads da Oficina Steam e atualizador integrado pelo GitHub.

---

## Índice

- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Guia Rápido e Funcionalidades](#guia-rápido-e-funcionalidades)
  - [1. Assistente Inicial (`Setup Wizard`)](#1-assistente-inicial-setup-wizard)
  - [2. Conversão Individual (`Individual`)](#2-conversão-individual-individual)
  - [3. Confirmação Pré-Conversão](#3-confirmação-pré-conversão)
  - [4. Conversão em Lote (`Em Lote`)](#4-conversão-em-lote-em-lote)
  - [5. Meus Mods (`Meus Mods`)](#5-meus-mods-meus-mods)
  - [6. Download da Oficina Steam (`Download`)](#6-download-da-oficina-steam-download)
  - [7. Histórico de Conversões (`Histórico`)](#7-histórico-de-conversões-histórico)
  - [8. Diagnóstico de Ambiente (`Ambiente`)](#8-diagnóstico-de-ambiente-ambiente)
  - [9. Atualizador Integrado (`Atualizações`)](#9-atualizador-integrado-atualizações)
  - [10. Configurações e Sobre (`Configurações`)](#10-configurações-e-sobre-configurações)
- [Tags / Placeholders de Saída](#tags--placeholders-de-saída)
- [Modo Linha de Comando (CLI)](#modo-linha-de-comando-cli)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Compartilhando uma Cópia Limpa](#compartilhando-uma-cópia-limpa)
- [Executando Testes](#executando-testes)
- [Contato, Créditos e Licença](#contato-créditos-e-licença)

---

## Requisitos

- **Windows 10 / 11**
- **Python 3.10+** (`3.13` recomendado) — marque **"Add Python to PATH"** durante a instalação
- **Left 4 Dead 2** instalado pela Steam (`AppID 550`)
- **Left 4 Dead 2 Authoring Tools** instalado na Biblioteca Steam → Ferramentas (`AppID 563`, fornece `studiomdl.exe` e `vpk.exe`)

Dependências Python ([`requirements.txt`](../requirements.txt)): `PySide6>=6.9.0`, `PySide6-Fluent-Widgets>=1.11.0`, `vpk>=1.4.0`, `vdf>=3.4`, `psutil>=5.9.0`.

---

## Instalação

### Opção A — Instalação Simples no Windows (Recomendado)

1. Baixe ou extraia a pasta do programa no seu PC (ex: `C:\L4D2-Survivor-Swapper-Tool\`).
2. Certifique-se de que **Left 4 Dead 2** e **Left 4 Dead 2 Authoring Tools** estejam instalados na Steam.
3. Dê dois cliques em [`_INSTALL_REQUIREMENTS.bat`](../_INSTALL_REQUIREMENTS.bat) para instalar todas as bibliotecas Python automaticamente.
4. Dê dois cliques em [`_RUN.bat`](../_RUN.bat) para abrir o programa (inicia sem janela de console via `pythonw`).

### Opção B — Via Terminal / PowerShell

```powershell
git clone https://github.com/SirCaveiraOFC/L4D2-Survivor-Swapper-Tool.git
cd L4D2-Survivor-Swapper-Tool
pip install -r requirements.txt
python app.py
```

*(Caso queira recompilar o [`MdlDecompilerCli.exe`](../tools/mdl_decompiler_cli/MdlDecompilerCli.exe) a partir do código-fonte VB.NET do Crowbar, veja [`build.ps1`](../tools/mdl_decompiler_cli/build.ps1) e [`NOTICE.txt`](../tools/mdl_decompiler_cli/NOTICE.txt).)*

---

## Guia Rápido e Funcionalidades

### 1. Assistente Inicial (`Setup Wizard`)

Na primeira execução (ou se algum caminho da Steam/Authoring Tools estiver faltando), o **Assistente de Configuração** detecta automaticamente suas bibliotecas Steam, Left 4 Dead 2 (`AppID 550`), `studiomdl.exe` + `vpk.exe` (`AppID 563`), `MdlDecompilerCli.exe`, e sincroniza o arquivo `%APPDATA%\ZeqMacaw\Crowbar 0.74\Crowbar Settings.xml` com backup `.bak`.

---

### 2. Conversão Individual (`Individual`)

1. Arraste qualquer `.vpk`, arquivo compactado `.zip` / `.rar` / `.7z` (com seletor caso haja múltiplos VPKs) ou pasta extraída para o Passo 1 — ou carregue direto de **Addons / Oficina do L4D2** ou via **Link da Oficina**.
2. Confira o **Sobrevivente de Origem** detectado automaticamente, os assets (`Corpo`, `Braços`, `VGUI`, `Física`) e a prévia decodificada das texturas VGUI (Lobby, HUD, Incapacitado — clique para ampliar).
3. Marque um ou mais sobreviventes de destino organizados nos cards **L4D1** e **L4D2** (ou use os atalhos `Todos os Outros`, `Grupo L4D1`, `Grupo L4D2`, `Limpar`).
4. Ajuste os templates de arquivo/título com tags clicáveis, metadados (`Autor`, `Versão`, `Descrição`), imagem de capa (`addonimage.jpg` / `.png`) e as **Opções de Conversão** agrupadas (`Assets do Modelo` e `Saída & Metadados`), e clique em **Iniciar Conversão**.

---

### 3. Confirmação Pré-Conversão

Antes de compilar, uma janela de resumo exibe a capa, arquivo de origem, pílulas de rota (`Origem -> Destinos`), nomes exatos dos `.vpk` que serão criados e opções ativas (em lote, navegue pelos itens usando **Anterior** / **Próximo** ou as setas `←` / `→`).

---

### 4. Conversão em Lote (`Em Lote`)

Adicione vários mods à fila por arquivos, pastas, Addons/Workshop locais ou vários links da Oficina Steam de uma só vez:
- Configure **Padrões Globais da Fila** (destinos padrão, template de nome/título e opções) e aplique em todos os itens com um clique.
- Ou desmarque **Usar Padrões Globais** no item selecionado para personalizar destinos, origem, capa e opções individualmente.

---

### 5. Meus Mods (`Meus Mods`)

Gerencie os mods de sobreviventes já presentes em `left4dead2/addons/` e `addons/workshop/`:
- 8 cards clicáveis dos personagens mostrando quem está ativo e eventuais conflitos.
- Filtre por nome/autor, pasta (`Addons` vs `Workshop`), sobrevivente/geração e status (`Ativo` / `Desativado`).
- Ative/desative direto no `addonlist.txt`, visualize capas ampliadas, exclua `.vpk`s ou carregue qualquer mod no conversor.

---

### 6. Download da Oficina Steam (`Download`)

Cole uma ou várias URLs/IDs da Oficina Steam para inspecionar os dados e baixar `.vpk`s direto para `Workshop_Downloads/`:
- Exibe inscritos, favoritos, visitantes, tamanho, nota em estrelas, datas, tags e capa (com suporte a GIFs animados e zoom).
- Detecta automaticamente mods que não são skin de sobrevivente (como `Script VScript`, `Campanha/Mapa`, `Arma`, `Infectado`, `HUD`, `Áudio`), liberando instalação normal em `addons/`.
- Gerencie sua biblioteca local em `Workshop_Downloads/` e envie skins direto para **Individual**, **Em Lote** ou `addons/`.
- Clique em **Ler Descrição Completa** (ou na caixa de resumo) para abrir a descrição formatada em BBCode completo da Steam.

---

### 7. Histórico de Conversões (`Histórico`)

Consulte conversões anteriores (concluídas, parciais, canceladas ou com erro), veja cada arquivo `.vpk` gerado, reabra a fonte no Swapper, abra a pasta de saída ou reinstale com detecção de conflitos em `addons/`.

---

### 8. Diagnóstico de Ambiente (`Ambiente`)

Confira rapidamente o status do Left 4 Dead 2, Authoring Tools (`studiomdl.exe`, `vpk.exe`), `MdlDecompilerCli.exe` e `Crowbar Settings.xml`, refaça a detecção automática ou abra o Assistente Inicial novamente.

---

### 9. Atualizador Integrado (`Atualizações`)

Mantenha o aplicativo atualizado direto pelo GitHub sem perder suas configurações nem seus mods:
- Verifica automaticamente **GitHub Releases** ou a branch configurada (`core/app_meta.py`).
- Mostra o Changelog / Notas da versão e a lista exata de arquivos e pastas alterados (`+ Novo`, `~ Modificado`, `- Removido`) antes de instalar.
- Preserva automaticamente dados locais (`settings.json`, `conversion_history.json`, `Swapped_Survivors/`, `Survivor_Swap/`, `Workshop_Downloads/`), cria backup de segurança, atualiza dependências se `requirements.txt` mudar e reinicia o aplicativo ao concluir.

---

### 10. Configurações e Sobre (`Configurações`)

Ajuste caminhos manuais (`L4D2`, `studiomdl.exe`, `vpk.exe`, `Saída`, `Workshop_Downloads`, `Swap Kit`), preferências (`Auto-Instalar`, `Modo Debug`), **Tema** (`Escuro` por padrão, com suporte a `Sistema` / `Claro`), **Idioma** (`Automático` / `en-US` / `pt-BR` / `es-ES`) e informações **Sobre**.

---

## Tags / Placeholders de Saída

Você pode clicar nas tags ou digitar qualquer combinação em **Nome do Arquivo** e **Título do Addon**:

| Tag | Substituído por | Exemplo |
|---|---|---|
| `{survivor}` | Nome do sobrevivente de destino (minúsculo no arquivo) | `Nick` / `nick` |
| `{origin}` | Nome do sobrevivente original do mod | `Zoey` / `zoey` |
| `{orig_title}` | Título original limpo (remove menções repetidas da origem) | `Emma Frost` |
| `{title}` | Sinônimo de `{orig_title}` | `Emma Frost` |
| `{generation}` | Geração do destino (`L4D1` ou `L4D2`) | `L4D2` |
| `{origin_generation}` | Geração da origem (`L4D1` ou `L4D2`) | `L4D1` |
| `{display_name}` | Nome de exibição capitalizado do destino | `Nick` |
| `{survivor_id}` | Identificador interno do modelo Source | `survivor_gambler` |

---

## Modo Linha de Comando (CLI)

Verificar ambiente:

```powershell
python app.py --check-env
```

Sincronizar configurações do Crowbar `0.74`:

```powershell
python app.py --apply-crowbar-settings --check-env
```

Converter um `.vpk` para sobreviventes específicos:

```powershell
python app.py --cli --source "Survivor_Swap\emma-zoey.vpk" --dest bill louis francis nick rochelle coach ellis --output-name "emma-{survivor}"
```

Ou portar para todos os outros 7 sobreviventes e instalar em `addons/`:

```powershell
python app.py --cli --source "Survivor_Swap\emma-zoey.vpk" --all-except-origin --output-name "emma-{survivor}" --install
```

Parâmetros úteis: `--output-dir`, `--origin`, `--title`, `--author`, `--version`, `--description`, `--no-arms`, `--no-vgui`, `--no-weapons`, `--keep-temp`.

---

## Estrutura do Projeto

```text
.
├── app.py                              # Ponto de entrada unificado (CLI e GUI)
├── _RUN.bat                            # Atalho silencioso no Windows (via pythonw)
├── _INSTALL_REQUIREMENTS.bat           # Instalador automático do requirements.txt
├── requirements.txt                    # Dependências Python
├── core/                               # Motor headless orientado a objetos
│   ├── addons_scanner.py               # Leitor de addons/workshop e gerenciador do addonlist.txt
│   ├── app_meta.py                     # Nome, versão semântica, autor e metadados GitHub
│   ├── archive_service.py              # Validação e extração segura de .zip/.rar/.7z
│   ├── config_manager.py               # Persistência de settings.json e resolução de caminhos
│   ├── crowbar_settings.py             # Validador/sincronizador XML do Crowbar 0.74 com .bak
│   ├── history_manager.py              # Persistência de conversion_history.json
│   ├── i18n.py                         # Detecção de idioma + traduções en-US/pt-BR/es-ES
│   ├── mdl_toolchain.py                # Wrappers MdlDecompilerCli, studiomdl.exe e subprocess cancelável
│   ├── models.py                       # Dataclasses tipadas, enum SurvivorId e SwapCancelledError
│   ├── qc_merger.py                    # Mesclador universal AST de .qc (corpo e braços)
│   ├── qc_parser.py                    # Parser .qc com suporte a aspas, comentários e chaves
│   ├── smd_splitter.py                 # Divisor automático de SMDs >20k triângulos para o StudioMDL
│   ├── steam_bbcode.py                 # Conversor BBCode da Steam Workshop para HTML estilizado
│   ├── steam_locator.py                # Localizador Steam/L4D2/Authoring Tools via Registro e VDF
│   ├── survivors.py                    # SurvivorRegistry (modelos, braços FPS, slots VGUI, kits)
│   ├── swap_engine.py                  # Pipeline transacional multi-destino e placeholders
│   ├── updater.py                      # Verificador de releases/tree no GitHub, ZIP stager e aplicador
│   ├── vpk_service.py                  # Extração segura de VPK (utf-8/latin-1), empacotamento e addoninfo
│   ├── vtf_decoder.py                  # Decodificador nativo de texturas .vtf para prévias VGUI
│   └── workshop_downloader.py          # Inspetor API/HTML da Steam Workshop e downloader de VPK
├── ui/                                 # Interface gráfica PySide6 + PySide6-Fluent-Widgets
│   ├── addon_ui_shared.py              # Tabelas, zoom, teardown seguro de QThread e painéis agrupados
│   ├── addons_browser_dialog.py        # Seletor addons/workshop e resolvedor de conflitos
│   ├── addons_page.py                  # Aba Meus Mods (slots + controle do addonlist.txt)
│   ├── batch_page.py                   # Aba Conversão em Lote com padrões globais e por item
│   ├── conversion_confirm_dialog.py    # Modal de confirmação pré-conversão
│   ├── download_page.py                # Central de Download da Workshop e biblioteca local
│   ├── environment_page.py             # Cartões visuais de diagnóstico L4D2 / Tools / Crowbar
│   ├── error_dialog.py                 # Modal de detalhes de erro com cópia para área de transferência
│   ├── history_page.py                 # Aba Histórico com reinstalação e reabertura em 1 clique
│   ├── main_window.py                  # Janela principal FluentWindow, navegação, tema e badge de atualizações
│   ├── settings_page.py                # Caminhos, aparência, idioma e Sobre
│   ├── setup_wizard.py                 # Assistente automatizado de primeira execução
│   ├── swap_page.py                    # Aba Conversão Individual, VGUI, progresso e logs
│   ├── theme.py                        # Paleta L4D2 (Amarelo/Vermelho/Preto/Branco), animações e repaint
│   ├── updates_page.py                 # Aba Atualizações com changelog e tabela de arquivos alterados
│   ├── widgets.py                      # Banner, drop zone, seletor de sobreviventes agrupado, zoom e badges
│   ├── workshop_description_dialog.py  # Visualizador completo em BBCode da descrição do mod
│   └── workshop_download_dialog.py     # Modal rápido de download por link/ID da Workshop
├── docs/                               # Documentação traduzida (PT-BR / ES-ES)
├── tools/mdl_decompiler_cli/           # CLI headless do Crowbar 0.74 em VB.NET + script de build
├── HUNK'S_SURVIVOR_SWAP_KIT/           # Templates base de QC/animação/rig por sobrevivente
├── legacy/                             # Scripts v1.x arquivados e Crowbar.exe antigo
└── tests/                              # Testes unitários e de UI headless (pytest)
```

---

## Compartilhando uma Cópia Limpa

Antes de compactar a pasta para enviar a outro usuário, remova arquivos pessoais/locais para que o destinatário tenha a experiência limpa de primeira execução:

- Exclua `settings.json`, `conversion_history.json` e `.update_manifest.json`.
- Esvazie ou exclua `Survivor_Swap/`, `Swapped_Survivors/`, `Workshop_Downloads/`, `.pytest_cache/`, `__pycache__/` e opcionalmente `legacy/`.

---

## Executando Testes

```powershell
pytest
```

---

## Contato, Créditos e Licença

- **Contato** — Email: [srcaveiraoficial@gmail.com](mailto:srcaveiraoficial@gmail.com)
- **GitHub** — [SirCaveiraOFC/L4D2-Survivor-Swapper-Tool](https://github.com/SirCaveiraOFC/L4D2-Survivor-Swapper-Tool)
- **Sr.Caveira** — Criador, arquitetura e automação do L4D2 Survivor Swapper Tool
- **ZeqMacaw** — Motor de decompilação [Crowbar](https://github.com/ZeqMacaw/Crowbar) (avisos de licença em [`tools/mdl_decompiler_cli/NOTICE.txt`](../tools/mdl_decompiler_cli/NOTICE.txt))
- **H.U.N.K** — Templates base `.qc` do `HUNK'S_SURVIVOR_SWAP_KIT`
- **Valve Corporation** — Source Engine SDK (`studiomdl.exe`, `vpk.exe`)

Consulte [`LICENSE`](../LICENSE) para detalhes da licença.
