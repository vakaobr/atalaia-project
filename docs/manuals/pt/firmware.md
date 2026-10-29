<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Guia do firmware para quem monta

Para quem monta uma caixa ou um adereço e tem de lhe pôr o software. Não precisas de escrever código. Precisas de um computador, de um cabo USB-C **de dados** e da placa. Os passos são os mesmos para todos os tipos de placa do projeto: a Field Box, o Satélite, o módulo de E/S e a placa modem do controlador. Em inglês: [Firmware guide for builders](../en/firmware.md).

> **Ainda não está pronto para o campo.** As versões do firmware no GitHub estão marcadas como pré-lançamento (*pre-release*) por isso mesmo. A Atalaia está em pré-alfa. Placas Heltec V4.3 a sério já foram gravadas e usadas numa bancada com o controlador de campo: arranque, rádio, botões, o ecrã OLED da própria placa, adoção por cabo USB e por código, e uma atualização pelo ar. Mais nada neste guia correu numa placa a sério. Os passos que dependem de hardware que não foi experimentado dizem **Ainda não testado numa placa real**.

O hardware está nos manuais de montagem: [Field Box](../../../hardware/field-box/BUILD.pt.md), [Satélite](../../../hardware/satellite/BUILD.md), [módulo de E/S](../../../hardware/io-pod/BUILD.md) (os dois últimos, em inglês). O controlador está no [guia de montagem do controlador](controller-setup.md).

## Índice

1. [O que gravas](#1-o-que-gravas)
2. [Obter o firmware: transferir uma versão publicada, ou compilá-lo](#2-obter-o-firmware-transferir-uma-versão-publicada-ou-compilá-lo)
3. [Grava-o](#3-grava-o)
4. [As opções de quem monta](#4-as-opções-de-quem-monta)
5. [Primeiro arranque e configuração](#5-primeiro-arranque-e-configuração)
6. [Adoção](#6-adoção)
7. [Atualizações pelo ar, e o que mais usa o Wi-Fi do campo](#7-atualizações-pelo-ar-e-o-que-mais-usa-o-wi-fi-do-campo)
8. [Uma caixa que não arranca](#8-uma-caixa-que-não-arranca)
9. [A placa modem](#9-a-placa-modem)
10. [As variantes do módulo de E/S](#10-as-variantes-do-módulo-de-es)

## 1. O que gravas

Há um só projeto de firmware e quatro imagens que podes compilar a partir dele.

| Imagem | Comando de compilação | Pasta de saída | Para | Usa-se num jogo |
| --- | --- | --- | --- | --- |
| Field Box | `python tools/docker_fw.py build` | `firmware/esp32/build/` | Uma Field Box, e também um Satélite (a mesma imagem, com menos peças) | Sim |
| Modem de rádio USB | `python tools/docker_fw.py modem` | `firmware/esp32/build-modem/` | A segunda placa, ligada ao controlador | Sim |
| Módulo de E/S | `python tools/docker_fw.py pod` | `firmware/esp32/build-pod/` | Uma placa que empresta os botões e o rádio a um telemóvel Android | Sim |
| Bancada | `python tools/docker_fw.py bench` | `firmware/esp32/build-bench/` | Uma placa nua na tua secretária: teclas escritas na consola USB, sem página de configuração, PIN de administração 1234 | **Nunca** |

Todas são feitas para a **Heltec WiFi LoRa 32 V4** (revisão V4.3 por omissão, V4.2 com uma alteração, vê a [secção 4](#4-as-opções-de-quem-monta)). Não grafes uma imagem feita para um tipo de placa noutro. De qualquer modo, uma caixa recusa uma atualização feita para outra variante ou outra placa.

## 2. Obter o firmware: transferir uma versão publicada, ou compilá-lo

Há duas maneiras. Transfere uma versão publicada se só queres pôr na placa o firmware do projeto. Compila-o tu se alteraste o código ou queres escolher opções de compilação (a região de rádio, a revisão da placa, as tuas próprias chaves).

### 2.1 Transferir uma versão publicada (o caminho fácil)

O projeto publica o firmware no GitHub: [a página de Releases](https://github.com/vakaobr/atalaia-project/releases). A primeira é a **v0.4.0**, marcada como **pré-lançamento**: pré-alfa e **não testada num campo**. Lê primeiro as notas dela.

Escolhe os ficheiros da tua placa:

| Estás a montar | Transfere | Notas |
| --- | --- | --- |
| Uma Field Box, ou um Satélite (a mesma imagem) | `atalaia-field-box-<version>-usb.zip` (esptool por USB) ou `atalaia-field-box-<version>-merged.bin` (gravador no browser) | O ficheiro simples `atalaia-field-box-<version>.bin` e o seu `.bin.release.json` servem para as atualizações pelo ar ([secção 7](#7-atualizações-pelo-ar-e-o-que-mais-usa-o-wi-fi-do-campo)); não precisas deles para gravar |
| O modem de rádio USB do controlador | `atalaia-modem-<version>-usb.zip` ou `-merged.bin` | A segunda placa, ligada ao controlador |
| Um módulo de E/S | `atalaia-io-pod-<version>-usb.zip` ou `-merged.bin` | |
| Nunca para um jogo | (a imagem de bancada não é publicada) | Compila-a tu, se precisares dela |

Todos são para a Heltec WiFi LoRa 32 V4.3, região de rádio europeia (EU868), com ouvir antes de falar ligado e com as chaves do projeto incluídas. Para uma V4.2, para Taiwan (AS923) ou para as tuas próprias chaves, compila-o tu ([2.2](#22-compilar-por-ti)).

**Confirma o que transferiste.** Transfere também o `SHA256SUMS` e compara. No Linux e no macOS, na pasta dos ficheiros (`shasum -a 256 -c SHA256SUMS` no macOS; os ficheiros que não transferiste são indicados como em falta, ignora-os):

```
sha256sum -c --ignore-missing SHA256SUMS
```

No `cmd` do Windows: `certutil -hashfile atalaia-field-box-0.4.0-usb.zip SHA256` e compara a linha com a que está no `SHA256SUMS`. As somas provam que o ficheiro é o que a página da versão publicada lista. A assinatura prova quem fez uma imagem da Field Box: o `.release.json` é assinado com a chave de versões da CI do projeto, em que todas as caixas confiam por omissão (`firmware/esp32/docs/RELEASE_SIGNING.md`). Uma caixa e um controlador verificam-na por ti antes de instalarem uma atualização.

**Grava o zip.** Descompacta-o. Nessa pasta segue a [secção 3](#3-grava-o) a partir da 3.1: os comandos são os mesmos, e o `README.txt` dentro do zip repete-os. A pasta tem o ficheiro `flash_args` que o comando usa, por isso salta a compilação e o passo `cd firmware/esp32/build`.

**Grava o ficheiro «merged» a partir de um browser** (Chrome ou Edge, sem Python): abre o gravador web da Espressif, [https://espressif.github.io/esptool-js/](https://espressif.github.io/esptool-js/), liga a placa (em modo de gravação, se não aparecer, [3.2](#32-encontrar-a-porta-da-placa)), define o endereço de gravação como `0x0`, escolhe o ficheiro `-merged.bin` e programa. O projeto ainda não o experimentou com uma placa real; o ficheiro é o mesmo que o comando esptool produz a partir do zip.

O número da versão publicada é o que a caixa mostra no arranque (`0.4.0`).

### 2.2 Compilar por ti

Precisas de:

- [Docker](https://docs.docker.com/get-docker/) (Docker Desktop no Windows e no macOS). Inicia-o.
- [Python 3](https://www.python.org/downloads/) e [git](https://git-scm.com/downloads).

Depois, num terminal (`cmd`, PowerShell, Terminal, qualquer shell):

```
git clone https://github.com/vakaobr/atalaia-project
cd atalaia-project
python tools/docker_fw.py build
```

No macOS e no Linux, usa `python3` se o `python` não for encontrado. A primeira compilação transfere as ferramentas de compilação e demora vários minutos (cerca de dez da primeira vez). Acaba com uma linha que nomeia o ficheiro `firmware/esp32/build/atalaia_esp32.bin`. Os outros ficheiros de que precisas estão na mesma pasta. Não precisas de os ler.

Uma compilação feita a partir de um clone mostra uma versão como `0.4.0+12.g1a2b3c4` (ou `0.5.0-dev.12+g1a2b3c4` entre versões publicadas): o número da versão publicada, o número de alterações desde então e o identificador do código. Também aparece no ecrã pequeno da placa, no arranque. Guarda uma nota dela junto da caixa. Para obteres exatamente o firmware de uma versão publicada, faz checkout da etiqueta dela (`git checkout v0.4.0`) e compila aí: um checkout limpo de uma etiqueta diz apenas `0.4.0`.

**Chaves.** Uma compilação feita por ti confia, por omissão, nas duas chaves de versões e nas duas chaves de modos do projeto, tal como os ficheiros publicados, por isso um controlador teu aceita as versões assinadas do projeto. As tuas compilações não são assinadas pelo projeto: assina-as com uma chave tua e dá às caixas a metade pública dela (`--release-keys=`, [secção 7](#7-atualizações-pelo-ar-e-o-que-mais-usa-o-wi-fi-do-campo)).

## 3. Grava-o

Gravar escreve a imagem na placa. Fazes isso com o **esptool**, uma ferramenta gratuita da Espressif. A porta USB-C da placa é a porta USB do próprio chip, por isso não há nenhum chip USB-série para o qual instalar um controlador.

**Windows e Docker.** O Docker no Windows não vê portas USB. Compila no Docker e depois grava a partir do próprio Windows. Se compilas dentro do WSL, copia a pasta de compilação para uma pasta do Windows e grava a partir daí.

### 3.1 Instalar o esptool uma vez

Usa um ambiente Python separado e esta versão (4.8.1, a que a compilação usa).

Windows (`cmd`):

```
python -m venv %USERPROFILE%\atalaia-flash
%USERPROFILE%\atalaia-flash\Scripts\python -m pip install esptool==4.8.1
```

macOS e Linux:

```
python3 -m venv ~/atalaia-flash
~/atalaia-flash/bin/python -m pip install esptool==4.8.1
```

Daqui em diante, `PY` quer dizer esse Python: `%USERPROFILE%\atalaia-flash\Scripts\python` no Windows, `~/atalaia-flash/bin/python` no macOS e no Linux. No PowerShell escreve-o como `& "$env:USERPROFILE\atalaia-flash\Scripts\python"`.

### 3.2 Encontrar a porta da placa

Monta primeiro as antenas. **Nunca ligues a placa sem a antena LoRa.** Liga a placa com um cabo USB-C **de dados**. Um cabo só de carga não mostra nada.

| Sistema | Onde aparece a porta | Notas |
| --- | --- | --- |
| Windows 10 e 11 | Uma porta `COM` nova (Gestor de Dispositivos, *Ports (COM & LPT)*; ID USB 303A:1001) | Não é preciso controlador. Na primeira placa testada, a porta só apareceu na própria porta USB-C do PC, não através de um hub |
| Linux | `/dev/ttyACM0` (ou `ttyACM1`...) | Junta-te uma vez ao grupo `dialout` (`sudo usermod -aG dialout $USER`) e depois volta a iniciar sessão |
| macOS | `/dev/cu.usbmodem...` (lista-as com `ls /dev/cu.usbmodem*`) | O projeto não testou no macOS |

Para listar as portas com a ferramenta: `PY -m serial.tools.list_ports -v`.

Se não aparecer nenhuma porta, mantém premido o botão **PRG** da placa, carrega e larga o **RST**, e depois larga o PRG. Isto é o modo de gravação (*download mode*). A porta pode desaparecer e voltar quando a placa reinicia. É normal.

### 3.3 Escrever a imagem

Vai à pasta de compilação e escreve todos os ficheiros com um só comando. Os exemplos usam `COM5`. Usa a tua porta, por exemplo `/dev/ttyACM0`.

Só na primeira gravação de uma placa nova, apaga-a. Isto apaga também as definições e qualquer adoção:

```
PY -m esptool --chip esp32s3 -p COM5 erase_flash
```

Depois escreve:

```
cd firmware/esp32/build
PY -m esptool --chip esp32s3 -p COM5 -b 921600 write_flash "@flash_args"
```

Mantém as aspas: o PowerShell lê um `@` solto de maneira diferente. O `flash_args` é um ficheiro que a compilação fez. Lista os ficheiros e onde vão. Se a ligação falhar, usa o modo de gravação, ou experimenta `-b 460800` ou `-b 115200`.

Para o modem e para o módulo de E/S, vai a `build-modem` ou a `build-pod`.

**É preciso instalar por USB uma vez, a partir da v0.5.** Uma caixa gravada com a v0.4.0 ou anterior tem a tabela de partições antiga (espaços de programa de 2 MB). A partir da v0.5 os espaços de programa têm 4 MB e uma atualização pelo ar não consegue mudar a tabela de partições, por isso grava essa caixa por USB uma vez, com o comando acima e **sem** `erase_flash`: as definições, as chaves e a adoção ficam onde estavam (as primeiras quatro partições da tabela não mudaram de sítio). Perde-se a partição de armazenamento, que mudou de sítio: a caixa formata-a no primeiro arranque e volta a obter os modos de jogo e o logótipo do campo na associação seguinte. Uma caixa ainda com a tabela antiga recusa-se a correr o firmware novo: o ecrã mostra *Instala por USB* e o registo diz `WRONG PARTITION TABLE`. Uma caixa a quem um firmware mais antigo ofereceu a imagem nova pelo ar volta sozinha à antiga. Depois dessa gravação por USB, as atualizações pelo ar funcionam como antes. O modem de rádio USB e o módulo de E/S partilham a tabela: um já gravado com a v0.4.0 ou anterior só regista `WRONG PARTITION TABLE` e continua a funcionar, mas grava-o também por USB uma vez (sem `erase_flash`) para ficar com a disposição nova.

### 3.4 Reiniciar e observar

Reinicia a placa com este comando. É a maneira fiável. O reinício de um programa de série não é:

```
PY -m esptool --chip esp32s3 -p COM5 --after hard_reset chip_id
```

Abre o registo e carrega em `Ctrl+]` para sair:

```
PY -m serial.tools.miniterm COM5 115200
```

Deves ver a versão do firmware, a memória e uma linha por cada peça encontrada. Uma peça que não está montada dá um aviso e a caixa continua. O registo pode avisar sobre os GPIO 33 a 37: as notas de bancada do projeto chamam a isso cosmético.

**Sem Python, no Chrome ou no Edge.** Faz um único ficheiro de imagem e grava-o no endereço `0x0` com a página web da Espressif. Numa shell bash:

```
docker run --rm -v "$PWD/firmware/esp32/build:/b" -w /b espressif/idf:v5.3.2 bash -c '. $IDF_PATH/export.sh > /dev/null && esptool.py --chip esp32s3 merge_bin -o atalaia-merged.bin @flash_args'
```

No `cmd` do Windows, usa o comando do [manual da Field Box](../../../hardware/field-box/BUILD.pt.md#11-primeira-gravação). O passo de junção funciona; a página web não foi experimentada.

## 4. As opções de quem monta

A maior parte das opções são opções de compilação. Dá-as ao `docker_fw.py`:

| O quê | Como | Por omissão |
| --- | --- | --- |
| Região de rádio | `--region=eu868` ou `--region=as923-tw` (Taiwan, 920-925 MHz) | EU868 |
| Ouvir antes de falar | `--lbt=on` ou `--lbt=off` | ligado |
| Chaves de modos | `--mode-keys=<key>[,<key>...]` (até 4, em hexadecimal ou base64) | As duas chaves do projeto |
| Chaves de versões | `--release-keys=<key>[,<key>...]` (até 4) | Nenhuma: toda a atualização é recusada |
| Versão | `--fw-version=0.4.1` | A do código |

Exemplo para um campo em Taiwan: `python tools/docker_fw.py build --region=as923-tw`. Compila o modem e o módulo de E/S com a mesma `--region`. Uma caixa recusa um jogo de outra região. Usa uma antena para a banda: uma antena de 868 MHz está errada a 920 MHz.

**Chaves de modos.** Uma caixa vai buscar ao controlador, como pacote assinado, um modo de jogo que lhe falte. Só aceita pacotes assinados por uma chave incluída no seu firmware. Por omissão são as duas chaves do registo do projeto (raiz `d9521a79030ce544`, CI `7275108d2e3fe583`), listadas em [docs/community/keys.md](../../community/keys.md). Não alteres isto, a não ser que tenhas o teu próprio registo de modos. O `--mode-keys` substitui a lista, por isso volta a juntar as chaves do projeto se as quiseres manter.

**Definições que editas num ficheiro.** Algumas definições não têm opção de linha de comandos. Depois de uma compilação, abre `firmware/esp32/build/sdkconfig` (para o modem `build-modem/sdkconfig`, para o módulo de E/S `build-pod/sdkconfig`), altera a linha, guarda e compila outra vez.

| O quê | Linha |
| --- | --- |
| Revisão V4.2 da placa (chip GC1109 ao lado do conector LoRa) | `CONFIG_ATALAIA_BOARD_HELTEC_V4_2=y` e `# CONFIG_ATALAIA_BOARD_HELTEC_V4_3 is not set` |
| Antena com mais de 2 dBi | `CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI=` o ganho dela, arredondado para cima |
| Chip de ecrã ST7789 | `CONFIG_ATALAIA_DISP_ST7789=y` e `# CONFIG_ATALAIA_DISP_ILI9341 is not set` |
| 12 ou 16 LEDs no anel | `CONFIG_ATALAIA_LED_COUNT=12` (ou 16) |
| Ecrã pequeno da placa de pernas para o ar | `CONFIG_ATALAIA_OLED_FLIP=y` |
| Sem iBeacon na Field Box (vem ligado por omissão) | `# CONFIG_ATALAIA_BOX_BEACON is not set` |
| O intervalo e a potência da baliza | `CONFIG_ATALAIA_BOX_BEACON_INTERVAL_MS=500` (100 a 10000), `CONFIG_ATALAIA_BOX_BEACON_TX_DBM=0` |

Nunca baixes o `CONFIG_ATALAIA_RADIO_FEM_GAIN_DB` nem o ganho da antena abaixo dos valores reais. Isso quebraria o limite legal de potência.

Se mudares `--region`, `--lbt`, uma opção de chaves, ou atualizares o repositório, a compilação pode voltar a fazer o ficheiro de definições a partir dos valores por omissão e as tuas edições perdem-se. Faz a edição outra vez. Guarda uma nota das tuas edições.

**Definições que não se fazem na compilação.**

- **O PIN de administração** não tem valor por omissão. Escolhes tu na página de configuração ([secção 5](#5-primeiro-arranque-e-configuração)). PIN fáceis, como 1234, são recusados.
- **O nome e a palavra-passe do Wi-Fi do campo** também se definem na página de configuração.
- **A chave de entrada do campo** é dada à caixa quando ela é adotada ([secção 6](#6-adoção)).
- **A baliza Bluetooth da caixa.** Uma Field Box ligada a um jogo emite um iBeacon para que um telemóvel que o ouça fique no lugar da caixa (o UUID da baliza vem da chave de entrada, o major é 45253 e o minor é o número do nó da caixa). Nada a definir na caixa: o Mestre de Jogo desliga-a para o campo todo na consola (**Campo**, **Balizas interiores**, **Caixas de campo como balizas**) e a entrada do jogo seguinte avisa as caixas. Usa a pilha Bluetooth da imagem (cerca de 160 KB a mais de flash e 25 KB a mais de RAM do que uma compilação sem ela) e está desligada entre jogos. A variante Wokwi e o modem não têm baliza.
- **A tua própria imagem de arranque.** A imagem do ecrã de arranque da caixa e dos ecrãs *pronta* é um ficheiro da compilação, `firmware/esp32/assets/splash.pgm` (a torre da Atalaia). Para compilar uma caixa com outra, faz um **PGM em texto** (primeira linha `P2`, depois `30 60`, o valor máximo e 1800 números, um por píxel, linha a linha; o `assets/splash.pgm` é um exemplo que podes abrir num editor de texto, e o GIMP e o ImageMagick escrevem o formato: `convert logo.png -resize 30x60! -depth 8 -compress none logo.pgm`) **com exatamente 30 x 60 píxeis**. Um píxel acende do meio do valor máximo para cima e fica escuro abaixo: a imagem tem uma só cor, branca no OLED pequeno e na cor de destaque, ampliada até 96 píxeis de altura, no ecrã grande; faz-a alta e estreita, como a torre. Depois substitui o `assets/splash.pgm` ou aponta a compilação ao teu ficheiro (`CONFIG_ATALAIA_SPLASH_LOGO` no menuconfig, *Boot splash*, um caminho relativo a `firmware/esp32/` ou absoluto; com o `docker_fw.py`, põe uma linha `CONFIG_ATALAIA_SPLASH_LOGO="assets/meu.pgm"` em `firmware/esp32/sdkconfig.defaults` e mantém o ficheiro dentro do repositório). A compilação transforma o ficheiro numa tabela em C e pára com uma mensagem se o ficheiro não for um PGM em texto de 30 x 60. Só a caixa de campo e o modem têm imagem de arranque. **As imagens de lançamento do projeto levam sempre a torre da Atalaia**; uma caixa com a tua imagem é uma compilação tua e não recebe atualizações de lançamento que não tenhas compilado tu.

## 5. Primeiro arranque e configuração

Uma Field Box ou um Satélite novo faz isto no primeiro arranque. A antena de 2,4 GHz tem de estar montada para a página de configuração.

1. O ecrã pequeno da placa mostra a torre e a versão durante 2 segundos. O ecrã grande (se estiver montado) e o pequeno passam a mostrar **PRIMEIRA CONFIGURAÇÃO** e o nome de uma rede Wi-Fi como `atalaia-1A2B`.
2. No telemóvel, liga-te a essa rede Wi-Fi. **Não tem palavra-passe**, por isso faz a configuração longe de quem joga.
3. A página de configuração abre sozinha na maioria dos telemóveis. Se não abrir, abre `http://192.168.4.1` no browser. A página está na língua da caixa, ou então na do telemóvel: inglês, português, alemão ou chinês tradicional.
4. Preenche a página (os nomes abaixo são os da página em português):
   - **Nome da caixa**: um nome para a caixa.
   - **Região de rádio**: tem de ser a região para que o firmware foi compilado.
   - **Número de equipas**: 2, 3 ou 4.
   - **PIN de administração**: 4 a 8 algarismos. Anota-o. 1234, 0000, uma sequência como 9876 e um par repetido como 1212 são recusados.
   - **Brilho do ecrã** e **Volume do som**.
   - **Chave de ligação ao campo** (opcional): os 64 algarismos hexadecimais que a organização te dá. Podes juntá-la depois, por adoção.
   - **Nome do Wi-Fi do campo** e **Palavra-passe do Wi-Fi do campo** (opcionais, mas precisos para as atualizações e para os modos de jogo obtidos: [secção 7](#7-atualizações-pelo-ar-e-o-que-mais-usa-o-wi-fi-do-campo)). O Wi-Fi do campo tem de ser de 2,4 GHz.
5. Toca em **Guardar e reiniciar**. A caixa reinicia.

Depois, uma caixa sem campo mostra **Emparelhar caixa** e um código de 6 algarismos ([secção 6](#6-adoção)). Uma caixa que já está adotada mostra **PRONTA**.

**Abrir outra vez a página de configuração.** Numa caixa que já foi configurada há duas maneiras. Nenhuma funciona durante um jogo.

- No teclado: carrega numa tecla, escreve o PIN de administração e `#`, vai à entrada **Configurar o Wi-Fi** (a seguir aos jogos), carrega em `#` e outra vez em `#` para confirmar.
- Na consola USB (um monitor de série na porta da caixa, a 115200): escreve `@setup` e o PIN de administração, e carrega em Enter.

A caixa mantém a adoção e a chave do campo. Substitui o que a página pede. A compilação de bancada não tem página de configuração.

**PIN esquecido.** Depois de cinco PIN errados, a caixa obriga-te a esperar 1, 2, 4... até 60 minutos. A espera sobrevive a um reinício. Se perdeste mesmo o PIN, apaga as definições ([secção 8](#8-uma-caixa-que-não-arranca)).

Ainda não testado numa placa real: a página de configuração e os ecrãs acima. A página foi testada num computador e no emulador.

## 6. Adoção

Uma caixa só joga no campo que a **adotou**. Adotar dá-lhe a chave de entrada do campo, uma vez. A organização faz isso na consola do controlador, no separador **Adotar**. Há três maneiras. Os pormenores para a organização estão no [Manual da organização](game-master.md) e no [Manual de operação da Field Box](field-box.md).

- **Por código, pelo rádio** (sem cabo, sem cartão). Uma caixa sem campo mostra **Emparelhar caixa** e um código de 6 algarismos, no ecrã grande e no ecrã pequeno. Na consola, em **Emparelhar por código (rádio)**, carrega em **Procurar caixas pelo rádio**, escolhe a caixa pelo nome e escreve o código. A caixa mostra então **Adotada** e o nome do campo. Um código errado dá um código novo. Três códigos errados fazem a caixa esperar um minuto. Dez param o emparelhamento até a caixa reiniciar. Feito em duas placas reais numa bancada. Ainda não testado num campo.
- **Por cabo USB.** Liga a caixa ao computador que corre o controlador. Na consola, carrega em **Procurar caixas** e depois em **Adotar**. A porta USB da caixa tem de estar ao alcance do controlador. Feito numa placa real numa bancada.
- **Por cartão de campo NFC.** Encosta o cartão de campo ao leitor NFC da caixa. O cartão é o segredo-mestre do campo: guarda-o fechado à chave. Ainda não testado numa placa real (nenhum leitor NFC foi montado numa placa real).

Uma caixa de outro campo pede o seu **PIN de administração**. **Mudar de campo** passa uma caixa para outro campo de propósito: no teclado carrega numa tecla, escreve o PIN e `#`, escolhe **Mudar de campo** (a entrada a seguir aos jogos e a **Configurar o Wi-Fi**) e confirma. A caixa mostra um código de emparelhamento e fica com o campo antigo até o novo a ter emparelhado. Um Satélite não tem teclado: usa o cabo USB.

## 7. Atualizações pelo ar, e o que mais usa o Wi-Fi do campo

Duas coisas usam o Wi-Fi do campo, e só entre jogos: as **atualizações de firmware** e os **modos de jogo que a caixa não tem** (obtidos do controlador, como pacotes assinados). Para as duas, a caixa precisa do **nome e da palavra-passe do Wi-Fi do campo** da página de configuração. Também os podes definir na consola USB: `@wifi <name> <password>`. O controlador tem de estar a correr com HTTPS ligado.

**As regras das atualizações de firmware.** A caixa só instala uma atualização se tudo isto for verdade:

- Nenhum jogo está a decorrer.
- A atualização está assinada por uma **chave de versões incluída no firmware da própria caixa** (`--release-keys`). Por omissão são as duas chaves de versões do projeto, por isso os ficheiros da Field Box de uma versão publicada no GitHub podem ser instalados como atualizações; uma caixa compilada com `--release-keys=` uma chave tua só confia nessa. As chaves do projeto e o que acontece se uma vazar estão em [RELEASE_SIGNING.md](../../../firmware/esp32/docs/RELEASE_SIGNING.md).
- A versão é mais alta do que a que corre.
- É da mesma variante e da mesma placa (uma imagem V4.2 nunca vai para uma V4.3).
- A bateria está a 30 % ou mais, se a caixa tiver medidor.

**O caminho curto.**

**Com as versões publicadas do projeto:** grava uma caixa uma vez por USB com uma versão publicada e depois carrega, no separador **Caixas** da consola, o `atalaia-field-box-<version>.bin` de uma versão posterior e o seu `.bin.release.json`. O `[firmware] release_keys` do controlador já tem por omissão as chaves do projeto. Carrega em **Atualizar para** (passo 5). **Com uma chave tua:**

1. Faz uma chave com `tools/firmware_release.py keygen`. Guarda o ficheiro privado em segurança e fora do repositório.
2. Compila as caixas com `--release-keys=<the public key>`. Grava-as por USB, uma vez. As atualizações não conseguem instalar um bootloader novo.
3. Põe a metade pública da chave na definição `[firmware] release_keys` do controlador.
4. Para uma atualização, compila uma versão mais alta (`--fw-version=0.4.1`), assina-a com `tools/firmware_release.py sign` e carrega a imagem e o seu `.release.json` no separador **Caixas** da consola. Carrega em **Atualizar para**.
5. A caixa descarrega-a, volta a verificá-la, instala-a e reinicia. Se a imagem nova falhar o autoteste, a caixa volta sozinha à antiga.

Feito uma vez numa placa real numa bancada, com uma chave descartável, enviada pelo controlador pelo rádio, numa rede Wi-Fi doméstica (cerca de 11 segundos). Ainda não testado num campo. Uma caixa gravada com firmware anterior às atualizações pelo ar precisa primeiro de uma gravação por USB, e uma caixa com a tabela de partições antiga (v0.4.0 ou anterior) também, antes de receber a v0.5 ([secção 3.3](#33-escrever-a-imagem)).

## 8. Uma caixa que não arranca

Segue a lista. Pára quando a caixa funcionar.

1. **O cabo e a porta.** Usa um cabo de dados, a própria porta USB-C do PC, sem hub. Fecha qualquer outro programa que tenha a porta (um monitor de série, o esptool).
2. **Energia.** Uma porta fraca ou uma bateria fraca dão reinícios e `brownout` no registo. Experimenta outra porta, com o interruptor desligado.
3. **Modo de gravação à mão.** Mantém premido o **PRG**, carrega e larga o **RST**, larga o PRG. Grava outra vez ([secção 3](#3-grava-o)).
4. **Tabela de partições errada.** Um ecrã que diz *Instala por USB* (registo: `WRONG PARTITION TABLE`) quer dizer que a caixa tem a tabela antiga: grava-a por USB uma vez ([secção 3.3](#33-escrever-a-imagem)).
5. **Compilação errada.** Confirma que gravaste `build`, e não `build-bench`, `build-modem` ou `build-pod`.
6. **Uma atualização que correu mal.** Uma imagem nova que não consegue confirmar-se é substituída pela antiga no reinício seguinte. Não precisas de fazer nada. Se ficar em ciclo, grava por USB.
7. **Apaga as definições** (nome, PIN, adoção, Wi-Fi) e mantém o programa:

   ```
   PY -m esptool --chip esp32s3 -p COM5 erase_region 0x9000 0x6000
   ```

8. **Apaga tudo e grava outra vez.** `erase_flash` e depois escreve ([secção 3.3](#33-escrever-a-imagem)). A caixa fica então nova: configura-a e adota-a outra vez.

Se o rádio não funcionar, confirma primeiro a revisão da placa ([secção 4](#4-as-opções-de-quem-monta)) e depois a antena. O [manual da Field Box](../../../hardware/field-box/BUILD.pt.md#13-resolução-de-problemas) tem uma tabela de avarias para cada peça.

## 9. A placa modem

O rádio do controlador é uma segunda Heltec V4 ligada à porta USB dele. Corre a imagem do modem.

1. Monta a **antena LoRa**. O modem não tem Wi-Fi, por isso não precisa de antena de 2,4 GHz.
2. Compila-o para a mesma revisão de placa e para a mesma região das caixas: `python tools/docker_fw.py modem` (com `--region=as923-tw` para Taiwan). Para uma V4.2, edita `firmware/esp32/build-modem/sdkconfig` como na [secção 4](#4-as-opções-de-quem-monta).
3. Grava a partir de `firmware/esp32/build-modem` como na [secção 3](#3-grava-o). Se a placa já estiver ligada a um controlador em funcionamento, pára primeiro o controlador: ele tem a porta.
4. Liga-a ao controlador. O ecrã pequeno dela mostra a torre e **MODO MODEM**, e depois o estado:
   - **LINK**: `waiting` (o controlador ainda não falou com ela: não está a correr, ou o modem está noutra porta), `OK`, ou `DOWN` (falou e depois parou durante 12 segundos).
   - O número do jogo, o canal, os pacotes enviados e recebidos com as falhas, e o tempo de emissão que resta.
   - **FALHA NO LORA** se o chip de rádio não arrancou.

   O ecrã está na língua das tuas caixas (inglês, português, alemão ou chinês tradicional). O controlador diz ao modem qual é de cada vez que se liga: a definição **língua das caixas** na consola da organização, ou, com `auto`, a língua da consola que criou o jogo. Antes de o controlador lhe ter falado, e no primeiro ecrã de arranque, o modem usa a língua da compilação, `en` por omissão. Para ser outra, põe `CONFIG_ATALAIA_MODEM_LANG="pt"` (ou `de`, `zh-tw`) em `firmware/esp32/build-modem/sdkconfig` e compila outra vez, como na [secção 4](#4-as-opções-de-quem-monta). Em português as palavras são `aguarda`, `OK`, `PERDIDO` e `FALHA NO LORA` (o tipo de letra pequeno não tem acentos); em alemão `wartet`, `OK`, `GETRENNT` e `FUNKFEHLER`; em chinês a ligação está na barra de cima (`等待`, `正常`, `離線`) e uma falha do rádio é `無線電錯誤`. Uma imagem de modem mais antiga, compilada antes disto, fica em inglês.
5. Põe a porta dela na definição `[modem] port` do controlador. No Linux costuma ser `/dev/ttyACM0`. O [guia de montagem do controlador](controller-setup.md) mostra como.

O modem é a única imagem cuja porta USB leva tramas de dados, por isso o registo dele está na UART0, e não no USB. Um modem assim já correu com o controlador e caixas reais numa bancada (2026-10-21). Ainda não testado num Raspberry Pi.

## 10. As variantes do módulo de E/S

Um módulo de E/S empresta os botões, o teclado, o anel, o som, o leitor NFC e o rádio a um telemóvel Android. As peças dele estão no [guia de montagem do módulo de E/S](../../../hardware/io-pod/BUILD.md) (em inglês).

- Compilação: `python tools/docker_fw.py pod` (`--region` como acima). Grava a partir de `firmware/esp32/build-pod`. Edita o `build-pod/sdkconfig` para uma V4.2.
- Um módulo de E/S não tem página de configuração, nem Wi-Fi, nem PIN de administração. Tem a antena de 2,4 GHz para o **Bluetooth** (`atalaia-pod-XXXX`), que é emparelhado e cifrado.
- A porta USB dele leva as tramas para o telemóvel, por isso o registo está no **GPIO 43** (transmissão da UART0), lido com um adaptador USB-série de 3,3 V a 115200 baud. Não está na porta USB.
- Opções de compilação do módulo de E/S, no `build-pod/sdkconfig`: uma cor para cada botão (`CONFIG_ATALAIA_POD_BTN1_TEAM="red"` e assim por diante), o pino do interruptor da caixa (`CONFIG_ATALAIA_POD_TAMPER_PIN`), Bluetooth ligado ou desligado. Deixa o `CONFIG_ATALAIA_POD_BLE_ENCRYPTED` ligado.
- As cores dos botões, o brilho do anel, o volume e o interruptor da caixa também podem ser definidos **pelo rádio**, na consola do GM, sem cabo ([guia de montagem do módulo de E/S, "Definições pelo rádio"](../../../hardware/io-pod/BUILD.pt.md#definições-pelo-rádio)); ficam guardados na memória flash do módulo. O número de LED, os pinos e o rádio continuam no `build-pod/sdkconfig`.
- Não usa o ecrã pequeno da placa.

Ainda não testado numa placa real: tudo isto. O firmware do módulo de E/S já correu num computador, com a app e o controlador. O Satélite não é uma variante: é a imagem da Field Box com menos peças montadas ([guia de montagem do Satélite](../../../hardware/satellite/BUILD.md), em inglês). O módulo de alvo ainda não pode ser montado ([a página dele](../../../hardware/target-addon/BUILD.md), em inglês).

Encontraste um passo que não corresponde ao que vês? Abre uma issue ou diz-nos nas [Discussions](https://github.com/vakaobr/atalaia-project/discussions).
