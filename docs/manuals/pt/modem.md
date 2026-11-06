<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Montar o modem de rádio

O **modem de rádio** é o rádio do controlador: uma placa Heltec WiFi LoRa 32 V4, gravada com a imagem do modem, ligada à porta USB do controlador. O controlador (um Raspberry Pi) não tem rádio próprio. Sem o modem, ele corre e a consola abre, mas nada chega às caixas e nada se ouve delas.

Esta página é o caminho todo, de uma placa nova até uma caixa a juntar-se a um jogo através do modem. Os outros guias remetem para aqui: o [guia do firmware](firmware.md), o [guia de montagem do controlador](controller-setup.md#3-preparar-a-placa-modem), o [Guia do telemóvel controlador](phone-controller.md) e o [Manual da organização](game-master.md). Para atualizar um modem que já tens, vai à [secção 10](#update-the-modem); para o usar com um telemóvel Android como controlador, à [secção 11](#with-a-phone-controller). Em inglês: [Set up the radio modem](../en/modem.md).

> **O que foi testado e o que não foi.** Um modem gravado assim correu com o controlador e caixas reais numa bancada (2026-10-21): o controlador em Docker no Windows (WSL2), o modem numa porta COM do Windows, a que o contentor chegava por uma pequena ponte COM-para-TCP (vê a nota avançada na secção 7). **Ainda não correu num Raspberry Pi**: os nomes de portas do Linux, o grupo `dialout` e os passos de `systemd` abaixo seguem os ficheiros do projeto e o guia do controlador, e nenhum Pi os correu. No macOS (2026-11-02, um Mac mini com Apple silicon, macOS 27) a imagem do modem e imagens de caixa foram gravadas como na secção 4, e o controlador em Docker chegou ao modem por uma ponte no Mac (secção 7) e registou `modem link up`; um controlador a correr diretamente no macOS não foi experimentado. O gravador no navegador não foi experimentado com uma placa real. Não testado num campo.

## 1. O caminho em resumo

1. Arranja as peças e monta a **antena LoRa** (secção 2).
2. Obtém a imagem do modem: transfere-a ou compila-a (secção 3).
3. Grava a placa (secção 4).
4. Confirma o ecrã da placa (secção 5).
5. Liga-a ao controlador e descobre a porta (secção 6).
6. Põe a porta nas definições do controlador e reinicia o controlador (secção 7).
7. Confirma que o controlador e o modem falam um com o outro (secção 8).
8. Junta uma caixa a um jogo através dele (secção 9).

Mais tarde: atualiza o modem quando uma versão nova o pedir (secção 10). Com um telemóvel como controlador, as secções 6 e 7 dão lugar à secção 11.

Se algo falhar, vai à tabela da [secção 12](#troubleshooting).

## 2. Antes de começar

| Precisas de | Notas |
| --- | --- |
| Uma **Heltec WiFi LoRa 32 V4**, só para o modem | Da mesma revisão (V4.3 ou V4.2) das tuas caixas. A V4.2 tem o chip GC1109 junto ao conector LoRa. Usa uma placa de que não precises como caixa: uma placa que é modem não é caixa |
| Uma **antena LoRa** para a tua banda | 868 MHz na Europa (2 dBi ou menos), 915-925 MHz em Taiwan. **Monta-a antes de a placa ter qualquer energia**, também para gravar. Alimentar a placa sem ela pode destruir o rádio. O modem não tem Wi-Fi, por isso não precisa de antena de 2,4 GHz |
| Um cabo USB-C **de dados** | Um cabo só de carga não mostra nenhuma porta. Curto. Para gravar, usa a porta USB do próprio computador, não um hub |
| Um computador para gravar | Windows 10 ou 11, Linux (serve o próprio Raspberry Pi) ou macOS, com [Python 3](https://www.python.org/downloads/) (serve o `python3` do próprio macOS) |
| A mesma **região de rádio** das caixas | EU868 (a predefinida) ou AS923-TW. Um modem e uma caixa feitos para regiões diferentes nunca falam. Decide isto antes da secção 3 |

## 3. Obter a imagem do modem

Há duas maneiras, como para as caixas (o [guia do firmware](firmware.md), «Obter o firmware»).

### 3.1 Transferir uma versão publicada (o caminho fácil)

1. Abre [a página das versões](https://github.com/vakaobr/atalaia-project/releases) e escolhe a mais recente. Todas estão marcadas como **pré-lançamento**: pré-alfa, não testadas num campo.
2. Transfere dois ficheiros: **`atalaia-modem-<versão>-usb.zip`** e **`SHA256SUMS`**. (`atalaia-modem-<versão>-merged.bin` é a mesma imagem num só ficheiro, para um gravador no navegador: [guia do firmware](firmware.md).) O modem não tem atualização pelo ar: grava-se sempre por USB.
3. Confirma a transferência. No Linux, na pasta dos ficheiros (os ficheiros que não transferiste aparecem como em falta: ignora-os):

   ```
   sha256sum -c --ignore-missing SHA256SUMS
   ```

   No macOS: `shasum -a 256 -c SHA256SUMS`. No Windows `cmd`: `certutil -hashfile atalaia-modem-0.8.0-usb.zip SHA256` e compara a linha com a do `SHA256SUMS`.
4. Descompacta-o para uma pasta própria. Tem o carregador de arranque, a tabela de partições, o programa, um ficheiro `flash_args` e um `README.txt` que repete os comandos abaixo.

   Windows `cmd`: `mkdir atalaia-modem` e depois `tar -xf atalaia-modem-0.8.0-usb.zip -C atalaia-modem` (ou clica com o botão direito, *Extrair tudo*). Linux e macOS: `unzip atalaia-modem-0.8.0-usb.zip -d atalaia-modem`.

**O que é o modem publicado:** a Heltec **V4.3**, a região **EU868** (868 MHz), escuta antes de emitir ligada, uma antena de 2 dBi suposta, as chaves do projeto incluídas, o ecrã em inglês até o controlador lhe dizer a língua das caixas. **Para uma V4.2, para Taiwan (AS923), para uma antena de mais de 2 dBi ou para um ecrã que arranque noutra língua, compila-o tu.**

### 3.2 Compilar por ti

Precisas de [Docker](https://docs.docker.com/get-docker/) (a correr), Python 3 e git. Num terminal:

```
git clone https://github.com/vakaobr/atalaia-project
cd atalaia-project
python tools/docker_fw.py modem
```

No macOS e no Linux usa `python3` se `python` não for encontrado. A primeira compilação demora vários minutos. Acaba com `Modem firmware: firmware/esp32/build-modem/atalaia_esp32.bin`. A pasta de onde se grava é **`firmware/esp32/build-modem`**: tem o `flash_args` e os ficheiros que ele nomeia.

Opções, todas só para a pasta de compilação do modem (a lista completa está no [guia do firmware](firmware.md), «As opções de quem monta»):

| O quê | Como |
| --- | --- |
| Taiwan | `python tools/docker_fw.py modem --region=as923-tw` (e uma antena de 915-925 MHz) |
| Uma antena de mais de 2 dBi | `--antenna-dbi=N`, o ganho indicado dela. Nunca o ponhas abaixo do valor real: é ele que mantém legal a potência radiada |
| Revisão de placa V4.2 | Compila uma vez e depois, em `firmware/esp32/build-modem/sdkconfig`, põe `CONFIG_ATALAIA_BOARD_HELTEC_V4_2=y` e `# CONFIG_ATALAIA_BOARD_HELTEC_V4_3 is not set`, e compila outra vez. Mudar `--region` ou a antena depois pode refazer esse ficheiro a partir dos valores por omissão: confirma as linhas |
| A língua do ecrã antes de o controlador falar | `CONFIG_ATALAIA_MODEM_LANG="pt"` (ou `de`, `zh-tw`) no mesmo ficheiro, e compila outra vez. O controlador define a língua de cada vez que se liga, por isso isto só conta nos primeiros segundos |

Dá ao modem e às caixas as mesmas opções. **Windows e Docker:** o Docker não vê portas USB. Compila no Docker e grava a partir do próprio Windows; se compilares dentro do WSL, copia primeiro `build-modem` para uma pasta do Windows.

## 4. Gravar a placa

Monta primeiro a antena. Liga a placa ao computador com o cabo de dados. Se o controlador estiver a correr com esta placa ligada, **pára-o primeiro** (`sudo systemctl stop atalaia-controller`): ele tem a porta.

### 4.1 Instalar o esptool uma vez

O esptool é a ferramenta de gravação gratuita da Espressif. Usa esta versão (4.8.1), num ambiente Python próprio.

Windows (`cmd`):

```
python -m venv %USERPROFILE%\atalaia-flash
%USERPROFILE%\atalaia-flash\Scripts\python -m pip install esptool==4.8.1
```

Linux e macOS:

```
python3 -m venv ~/atalaia-flash
~/atalaia-flash/bin/python -m pip install esptool==4.8.1
```

Num Raspberry Pi OS ou Ubuntu que diga `ensurepip is not available`, corre primeiro `sudo apt install python3-venv`. O teste em macOS usou o esptool 4.12.0 com o pyserial 3.5 (`~/atalaia-flash/bin/pip install esptool pyserial`), e também gravou as imagens.

### 4.2 Encontrar a porta da placa

| Sistema | Onde aparece a porta | Como a ver |
| --- | --- | --- |
| Windows 10 e 11 | Uma **COM** nova, ID USB 303A:1001. Não é preciso nenhum controlador (driver) | Gestor de dispositivos, *Portas (COM e LPT)*; ou `%USERPROFILE%\atalaia-flash\Scripts\python -m serial.tools.list_ports -v` |
| Linux | `/dev/ttyACM0`, ou `ttyACM1`... | `ls /dev/ttyACM*`, ou `dmesg \| tail` logo depois de ligares |
| macOS | `/dev/cu.usbmodem...` (por exemplo `/dev/cu.usbmodem31101`). Não é preciso nenhum controlador (driver). Usa o nome `cu.`, não o `tty.` | `ls /dev/cu.usbmodem*` |

Se não tiveres a certeza de qual é a placa, desliga-a, lista as portas, volta a ligá-la e lista outra vez: a nova é a placa. No macOS, com várias placas ligadas, `ioreg -p IOUSB -l -w0 | grep -E '"USB Serial Number" = "[0-9A-F]{2}:'` mostra o MAC de cada placa (o seu número de série USB), e `~/atalaia-flash/bin/python -m esptool --chip esp32s3 -p /dev/cu.usbmodem31101 read_mac` mostra o MAC da placa nessa porta (reinicia a placa).

**Só no Linux: o grupo `dialout`.** O teu utilizador precisa dele para abrir a porta. Confirma com `groups`; se faltar `dialout`, corre `sudo usermod -aG dialout $USER` e depois **sai da sessão e entra outra vez**. Sem isso o esptool diz `Permission denied`.

Se não aparecer nenhuma porta: outro cabo, a porta USB do próprio computador, sem hub. Depois entra em modo de transferência à mão: mantém premido **PRG**, prime e solta **RST**, solta **PRG**. A porta pode desaparecer e voltar quando a placa reinicia. É normal.

### 4.3 Escrever a imagem

Entra na pasta que tem o ficheiro `flash_args`: a pasta descompactada (3.1) ou `firmware/esp32/build-modem` (3.2). Depois corre os comandos do teu sistema, com **a tua porta** no lugar da mostrada. Mantém as aspas à volta de `@flash_args`.

**Apagar primeiro ou não?** Uma **placa nova**, ou uma que antes foi caixa ou outra coisa: apaga-a primeiro. Isso limpa também as definições, as chaves e a adoção de caixa que ela possa ter, e que um modem não deve levar. Regravar um modem que já corre a imagem do modem: não é preciso.

Windows (`cmd`, porta `COM5` como exemplo):

```
cd atalaia-modem
%USERPROFILE%\atalaia-flash\Scripts\python -m esptool --chip esp32s3 -p COM5 erase_flash
%USERPROFILE%\atalaia-flash\Scripts\python -m esptool --chip esp32s3 -p COM5 -b 921600 write_flash "@flash_args"
```

Na PowerShell escreve o Python como `& "$env:USERPROFILE\atalaia-flash\Scripts\python"`.

Linux (também num Raspberry Pi):

```
cd atalaia-modem
~/atalaia-flash/bin/python -m esptool --chip esp32s3 -p /dev/ttyACM0 erase_flash
~/atalaia-flash/bin/python -m esptool --chip esp32s3 -p /dev/ttyACM0 -b 921600 write_flash "@flash_args"
```

macOS (a escrita foi feita assim num Mac, para o modem e para caixas):

```
cd atalaia-modem
~/atalaia-flash/bin/python -m esptool --chip esp32s3 -p /dev/cu.usbmodem31101 erase_flash
~/atalaia-flash/bin/python -m esptool --chip esp32s3 -p /dev/cu.usbmodem31101 -b 921600 write_flash "@flash_args"
```

Para uma compilação, troca `cd atalaia-modem` por `cd firmware/esp32/build-modem` (a partir da pasta do repositório). Salta a linha `erase_flash` quando não apagares.

A escrita acaba com `Hash of data verified.` para cada ficheiro e `Hard resetting via RTS pin...`. Se a ligação falhar: modo de transferência à mão (acima), ou `-b 460800` ou `-b 115200`.

**Vens da v0.4.0 ou anterior?** Um modem gravado com a v0.4.0 ou anterior tem a tabela de partições antiga (ranhuras de programa de 2 MB). A partir da v0.5.0 as ranhuras são de 4 MB. A tabela antiga só faz o modem novo registar `WRONG PARTITION TABLE` e ele continua a funcionar, mas grava-o uma vez por USB como acima, **sem** `erase_flash`, para ficar com a disposição nova. O modem não mostra nada disto no ecrã, e o registo dele não vai pelo USB: vê a tabela da secção 10.

**Não abras a porta USB do modem com um monitor série** (miniterm, PuTTY, o monitor do Arduino) para ver um registo, como o guia faz com uma caixa. No modem essa porta leva as tramas de dados do controlador, não texto. O registo do modem está na UART0 (GPIO 43 e 44) e precisa de um adaptador USB-série de 3,3 V. Raramente é preciso: o ecrã diz o que importa.

## 5. Confirmar o ecrã da placa

O modem reinicia sozinho depois da escrita. Se o ecrã ficar apagado, desliga a placa e volta a ligá-la. O ecrã pequeno mostra então:

1. Durante cerca de 2 segundos, o ecrã de arranque: a torre da Atalaia, **ATALAIA**, **MODEM MODE** e a versão.
2. O ecrã de estado, sob uma barra com **MODEM MODE**:

```
LINK       waiting     o controlador: OK, DOWN, ou waiting
IDLE     no game       o número do jogo (GAME 4660), ou IDLE no game
CH   869.525 MHz       o canal em que o rádio está (921.500 MHz em Taiwan)
TX 0         fail 0    pacotes enviados, e falhas
RX 0         auth 0    pacotes passados ao controlador, e falhas a decifrar
DUTY  ...    left      o tempo de emissão que resta
```

Sem controlador ainda, **`LINK waiting`** está certo. É um modem gravado e saudável. Qualquer outra coisa:

- **RADIO FAULT** no lugar das últimas linhas: o chip de rádio não arrancou. Secção 12.
- A torre e as palavras de uma Field Box (um ecrã de configuração ou PRONTA): gravaste a imagem da caixa. Grava outra vez a partir dos ficheiros `modem`.
- Nada, de todo: secção 12.

Agora desliga a placa e leva-a ao controlador, ou deixa-a ligada se gravaste no Pi.

(Este ecrã mostra o inglês até o controlador falar com o modem, e depois fica na língua das caixas: `aguarda`, `PERDIDO`, `FALHA NO LORA` em português.)

## 6. Ligar ao controlador e descobrir a porta

Liga o modem a uma das portas USB do Raspberry Pi, com a antena montada e um cabo de dados curto. Prefere uma porta do próprio Pi a um hub. No Pi:

```
ls /dev/ttyACM*
```

Um nome (normalmente `/dev/ttyACM0`) é o modem. Se uma Field Box também estiver ligada (para a adotar por USB), há dois, e o número depende de qual veio primeiro. Para um nome que não mude, usa o `by-id`:

```
ls -l /dev/serial/by-id/
```

Lista nomes como `usb-Espressif_USB_JTAG_serial_debug_unit_<o MAC da placa>-if00`, cada um a apontar para um `ttyACM`. Desliga o modem e corre outra vez para ver qual desaparece. O nome by-id serve como `[modem] port` e o controlador compara-o com as portas USB da adoção pelo dispositivo real que está por trás, por isso a adoção nunca toca no modem. O nome by-id é conselho do projeto lido no código; não foi corrido num Pi.

## 7. Pôr a porta nas definições do controlador e reiniciá-lo

Se o controlador ainda não estiver instalado, faz primeiro a [secção 4 do guia de montagem do controlador](controller-setup.md#4-instalar-o-controlador) e volta: o passo 4 de lá é este.

1. Edita o ficheiro de definições: `sudo nano /etc/atalaia/controller.toml`.
2. Na secção `[modem]`, põe a porta que encontraste:

   ```
   [modem]
   port = "/dev/ttyACM0"
   baudrate = 921600
   ping_interval_s = 5.0
   ```

   Deixa `baudrate` e `ping_interval_s` como estão. Uma `port` vazia, ou nenhuma secção `[modem]`, quer dizer **sem rádio**: o controlador diz no registo `no modem port configured: the controller runs without a radio`. A mesma definição pode ser dada pela variável de ambiente `ATALAIA_MODEM_PORT`.
3. Em `[radio]`, `region` tem de ser a região para que o modem e as caixas foram feitos (`eu868` ou `as923-tw`).
4. Guarda e reinicia o controlador. Ele só lê o ficheiro quando arranca:

   ```
   sudo systemctl restart atalaia-controller
   sudo systemctl status atalaia-controller
   ```

   Deve dizer `active (running)`. O ficheiro de `systemd` deixa o serviço abrir `/dev/ttyACM*` e `/dev/ttyUSB*`, e o utilizador `atalaia` está em `dialout` (guia de montagem do controlador, secção 4, passo 3), por isso não é preciso mais nada para a porta.

Noutro computador, `port` é o nome que o sistema lhe dá: `COM5` no Windows, `/dev/cu.usbmodem31101` no macOS (um controlador a correr diretamente no macOS não foi experimentado).

**Controlador em Docker no Windows ou no macOS (avançado).** O Docker Desktop e o WSL não passam uma porta série USB para um contentor. O caminho suportado é correr o controlador diretamente no sistema. Se tiveres mesmo de usar Docker, liga a porta ao TCP no anfitrião (um pequeno programa que serve a porta COM numa porta TCP local: o `tools/serial_bridge.py` do repositório, mais um relé se o contentor não alcançar o loopback do anfitrião) e dá ao contentor um URL do pyserial como porta: `port = "socket://host.docker.internal:7601"` (o número é só um exemplo). O controlador abre a porta com o `serial_for_url` do pyserial, por isso os URL `socket://` funcionam, e foi assim que a bancada correu. A ponte corre fora do controlador (inicia-a antes do controlador e mantém-na a correr), e o ecrã do modem e as verificações da secção 8 valem como antes.

No macOS (tanto com Colima como com Docker Desktop) a bancada fez o mesmo: o `tools/serial_bridge.py` do repositório a correr diretamente no Mac com o `~/atalaia-flash/bin/python` (`python tools/serial_bridge.py /dev/cu.usbmodem... 7600 --baud 921600`), a servir `/dev/cu.usbmodem...` na porta TCP 7600, a definição `port = "socket://host.docker.internal:7600"` e o contentor iniciado com `--add-host host.docker.internal:host-gateway`. O controlador registou `modem link up` (2026-11-02). **Um só programa por porta série, sempre**: uma ponte, e nenhum esptool nem monitor de série na porta enquanto ela corre. Abrir a porta no macOS pode reiniciar a placa, por isso o ecrã inicial do modem pode voltar a aparecer: não faz mal.

## 8. Confirmar que o controlador e o modem falam

**No ecrã do modem**, até cerca de 5 segundos depois de o controlador arrancar: `LINK waiting` passa a **`LINK OK`**. Se a língua das caixas (a definição **língua das caixas** na consola) não for o inglês, o ecrã passa também para ela: `LINK aguarda`, `LINK wartet`, ou `等待`/`正常`/`離線` na barra.

**No registo do controlador:**

```
sudo journalctl -u atalaia-controller -n 50 | grep -i modem
```

Deves ver `atalaia.modem INFO modem link up` e, mesmo antes, `atalaia.modem INFO modem: {...}`: a identidade do modem, com o `fw_version` e a `region`. Uma falha aparece como `cannot open the modem at /dev/ttyACM0: ...`, `modem missed ping 1 of 3` ou `modem link lost; reconnecting`.

**Consegue avisar das caixas presas?** A partir da v0.9.0 (ainda não publicada; até lá, compila-a a partir do `main`, secção 3.2), a identidade do modem diz também `"games": true`. Um modem assim avisa o controlador quando ouve uma caixa que continua num jogo já terminado (uma caixa que estava desligada quando o jogo acabou), e o controlador liberta-a voltando a enviar o fim desse jogo. Funciona com um Raspberry Pi como controlador e com um telemóvel controlador (secção 11). Uma imagem do modem da v0.8.0 ou anterior não o faz: um controlador Raspberry Pi da v0.9.0 regista então uma vez `the radio modem's firmware cannot report boxes still in an ended game`, o separador **Caixas** da consola diz que o modem de rádio não consegue dizer que caixas ficaram num jogo terminado, e um telemóvel controlador di-lo no ecrã, em **Rádio**. Atualiza o modem para ter a recuperação automática (secção 10); até lá, tira essa caixa do jogo na própria caixa ([manual da Field Box](field-box.md#take-a-box-out-of-its-game)).

**Na consola da organização** (vê o [Manual da organização](game-master.md)): a etiqueta em cima à direita diz **Rádio: ligado**. `a ligar` e `em baixo` ainda não são bom sinal, e **sem modem** quer dizer que a definição está vazia. Se o modem cair, um alerta diz **Rádio em baixo: o modem USB não responde.**, e **Rádio de volta.** quando volta. O separador **Controlador** mostra **Rádio**, **Modem** (o firmware do modem e a versão) e **Religações do modem**: uma contagem que não pára de subir quer dizer cabo, porta ou energia com problemas.

**Mais duas verificações, nas Definições da consola:**

- **Região.** Em **Região de rádio**, nenhuma mensagem vermelha sobre o modem. Se disser *O modem USB foi feito para …, mas o campo está em …*, o modem e o campo discordam da região e nenhum jogo pode começar (secção 12).
- **Procurar.** Em **Canal de rádio do campo**, toca em **Procurar**. O modem escuta os canais possíveis, cerca de 60 segundos no total, repartidos entre eles, e lista-os do mais calmo para o mais ruidoso. Nada muda até aceitares um canal. Não emite nada, e só funciona com um rádio que arrancou: a consola diz *O modem USB não tem chip de rádio* se não arrancou.

## 9. Uma caixa junta-se a um jogo através do modem

Este é o teste a sério: uma caixa e o modem ouvem-se. Precisas de uma caixa adotada (mostra **PRONTA** depois de a ligares), na mesma região, com a antena montada, a poucos metros do modem.

1. Se a caixa for nova, adota-a: separador **Adotar**, por cabo USB, por cartão ou por **Emparelhar por código (rádio)** (vê o [Manual da organização](game-master.md)). O emparelhamento por código usa o rádio do modem.
2. Cria um jogo (separador **Jogo**, **Criar jogo**). Abre a janela **Caixas para este jogo**.
3. Liga a caixa. Em cerca de 20 segundos aparece na lista. Toca em **Procurar caixas** para perguntar já. Uma caixa que não apareça não ouve ou não é ouvida: secção 12.
4. Marca a caixa, escolhe o **Papel** dela e toca em **Convidar**. O **Estado** passa por **a enviar**, **convidada**, **aceitou, a juntar-se**, **juntou-se**.
5. No ecrã do modem, **JOGO** mostra agora o número do jogo e **TX** e **RX** sobem. No ecrã da caixa diz que está no jogo.

Se aparecer **juntou-se**, o caminho de rádio funciona nos dois sentidos. Termina o jogo no separador **Jogo** quando acabares (nada começa até o começares). O resto está no [Manual da organização](game-master.md).

<a id="update-the-modem"></a>

## 10. Atualizar o modem

O modem **não tem atualização pelo ar**: uma imagem nova escreve-se sempre por USB, como na secção 4.

### Quando o atualizar

- As notas de uma versão nova dizem que o modem mudou. Vê a [página das versões](https://github.com/vakaobr/atalaia-project/releases) e o CHANGELOG.
- O registo do controlador diz `the radio modem's firmware cannot report boxes still in an ended game`, ou o separador **Caixas** da consola, ou o ecrã de um telemóvel controlador em **Rádio**, diz que o modem de rádio não consegue dizer que caixas ficaram num jogo terminado. Isso precisa de uma imagem do modem da **v0.9.0** (ainda não publicada; até lá, compila-a a partir do `main`, secção 3.2).
- Foi gravado com a v0.4.0 ou anterior (a tabela de partições antiga, secção 4.3).

Para ver que versão um modem tem: o separador **Controlador** da consola, **Modem**, ou o `fw_version` no registo do controlador (secção 8).

Um modem e um controlador de versões diferentes continuam a falar: um controlador mais novo simplesmente não usa o que um modem mais antigo não sabe fazer. Não tens de atualizar os dois no mesmo dia, mas uma novidade que precise do modem só funciona quando os dois forem novos.

### Como o atualizar

1. Faz isto entre jogos: enquanto o modem está desligado, nenhuma caixa ouve o controlador.
2. Obtém a imagem nova: transfere-a e confirma-a (secção 3.1), ou compila-a com as mesmas opções de antes (secção 3.2).
3. Pára o controlador, para a porta ficar livre: `sudo systemctl stop atalaia-controller` num Raspberry Pi. Num telemóvel controlador, toca em **Parar o controlador** e desliga o modem do telemóvel.
4. Liga o modem ao computador com que gravas (num Pi, pode ficar onde está).
5. Escreve a imagem como na secção 4.3. Não precisas de `erase_flash`: o modem não guarda definições nem chaves suas.
6. Confirma o ecrã: o arranque mostra a versão nova (secção 5).
7. Volta a ligá-lo ao controlador e arranca o controlador: `sudo systemctl start atalaia-controller` num Pi, ou liga-o ao telemóvel e toca em **Arrancar o controlador**.
8. Confirma como na secção 8: **LINK OK**, o `fw_version` novo no registo e no separador **Controlador**. A partir da v0.9.0, a identidade no registo diz também `"games": true`.

<a id="with-a-phone-controller"></a>

## 11. Com um telemóvel controlador

Um telemóvel Android pode ser o controlador, com este modem como rádio ([Guia do telemóvel controlador](phone-controller.md)). O modem é a mesma placa e a mesma imagem que para um Raspberry Pi: as secções 2 a 5 não mudam. Ainda não experimentado com um telemóvel a sério.

### Modem de rádio USB ou módulo de E/S

Um telemóvel controlador também pode usar um **módulo de E/S** como rádio. O modem é o melhor rádio para as caixas; o módulo junta botões, luzes e uma sirene para o telemóvel.

| | Modem de rádio USB | Módulo de E/S |
| --- | --- | --- |
| Ligação ao telemóvel | Só USB | USB ou Bluetooth |
| Jogos, atualizações de firmware, procura de canal | Sim | Sim |
| Convites, fim de jogo, emparelhamento por código | Sim | Só com um firmware do módulo que passe estas tramas |
| Caixas presas num jogo terminado avisadas e libertadas sozinhas | Sim, a partir da v0.9.0 (ainda não publicada) | Não, nunca |

### Ligá-lo ao telemóvel

1. Monta a antena antes de a placa ter energia.
2. Liga o modem ao telemóvel com um cabo USB-C de dados curto (um cabo USB-C para USB-C, ou um adaptador OTG se o telemóvel precisar). O telemóvel alimenta a placa.
3. Na app, **Controlador de campo**, em **Rádio**, toca em **Procurar módulos**. O modem aparece na lista, como um módulo por USB. Toca nele. Se o Android perguntar se a app pode usar o dispositivo USB, autoriza. O controlador distingue um modem de um módulo pela resposta.
4. Toca em **Arrancar o controlador**. O ecrã diz **Rádio ligado**, e o ecrã do modem diz **LINK OK**.

O rádio escolhe-se antes de arrancar: para o mudar, toca primeiro em **Parar o controlador** (**Para mudar o rádio, para o controlador.**). Com um modem anterior à v0.9.0, o ecrã diz em **Rádio** que o firmware dele não consegue dizer que caixas ficaram num jogo terminado: atualiza-o (secção 10).

<a id="10-resolução-de-problemas"></a>
<a id="troubleshooting"></a>

## 12. Resolução de problemas

| O que vês | Causa provável e o que fazer |
| --- | --- |
| Não aparece nenhuma porta quando a placa está ligada | **Cabo só de carga**: experimenta outro, de dados. Depois a porta USB do próprio computador, não um hub. Depois o modo de transferência à mão: mantém premido **PRG**, prime **RST**, solta **PRG**. Windows: a porta está em *Portas (COM e LPT)* com o ID 303A:1001 |
| esptool: `Permission denied` (Linux) | O teu utilizador não está em `dialout`: `sudo usermod -aG dialout $USER`, e sai da sessão e entra outra vez |
| esptool: `could not open port`, `Access is denied` (Windows), `Resource busy` | **Outro programa tem a porta**: um monitor série, um segundo esptool, o Arduino IDE, ou o controlador. Fecha-o, pára o controlador (`sudo systemctl stop atalaia-controller`), desliga e liga a placa e tenta outra vez |
| esptool: `Failed to connect`, `No serial data received` | Porta errada (vê a secção 4.2), sem cabo de dados, ou o chip não está em modo de transferência: faz-o à mão. Experimenta `-b 460800` e depois `-b 115200` |
| No Ubuntu com ambiente gráfico a porta fica ocupada alguns segundos depois de ligar | O ModemManager sonda as portas série novas. Espera ou, se não usas banda larga móvel, `sudo systemctl disable --now ModemManager`. Não visto pelo projeto |
| O ecrã está apagado depois de gravar | Desliga e volta a ligar. Confirma o cabo. Se o ecrã estiver de cabeça para baixo, compila com `CONFIG_ATALAIA_OLED_FLIP=y`. Um ecrã apagado não pára o modem: a verificação é o registo do controlador e a consola |
| O ecrã mostra ecrãs de caixa | Gravaste a imagem da Field Box. Grava `modem` outra vez |
| **`LINK waiting`** não sai dali | O controlador não fala com esta placa: não está a correr (`systemctl status atalaia-controller`), `[modem] port` está vazio ou nomeia outra porta, o controlador não foi reiniciado depois da edição, ou outro programa tem a porta. Vê o registo (secção 8) e `ls /dev/ttyACM*` |
| Registo: `cannot open the modem at ...: No such file or directory` | O nome da porta está errado, ou a placa não está ligada. Secção 6; o nome pode mudar se ligares a placa a outra porta USB ou reiniciares com duas placas (usa o nome `by-id`) |
| Registo: `cannot open the modem ...: Permission denied` | O utilizador `atalaia` não está em `dialout` (guia de montagem do controlador, secção 4, passo 3): `sudo usermod -aG dialout atalaia` e reinicia o serviço |
| `LINK` alterna entre OK e DOWN, o registo está cheio de `modem missed ping`, sem erro ao abrir | **Outro programa tem a mesma porta aberta.** No Linux um segundo a abrir não é recusado: os dois partilham os bytes. `sudo fuser -v /dev/ttyACM0` mostra qual. Fecha-o |
| **`LINK DOWN`** ou **Rádio em baixo: o modem USB não responde.**, e as **Religações do modem** não param de subir | O modem respondeu e depois parou 12 segundos: o controlador parou ou perdeu a porta. Confirma `systemctl status`, o cabo (curto, de dados, bem encaixado), a energia da porta USB (uma porta fraca, um hub barato ou um powerbank em baixo) e se a placa reiniciou (o ecrã de arranque volta a aparecer). Religa-se sozinho |
| **`RADIO FAULT`** (**FALHA NO LORA**) | O chip de rádio não arrancou. O ecrã dá o motivo (por exemplo `SX1262 not found (BUSY stuck)`): anota-o. Confirma a revisão para que compilaste (a V4.2 e a V4.3 diferem: secção 3.2), depois o cabo, depois experimenta outra placa. O modem continua a falar com o controlador, por isso a consola diz **Rádio: ligado** e o **Procurar** diz que não há chip de rádio |
| Registo: `WRONG PARTITION TABLE` | O modem tem a tabela antiga (v0.4.0 ou anterior). Funciona, e só o diz na UART0, por isso podes não o ver. Grava-o uma vez por USB sem `erase_flash` (secção 4.3). O `README.txt` do zip diz o mesmo |
| Consola, Definições: **O modem USB foi feito para …, mas o campo está em …** | A região do modem e a do campo diferem. Nenhum jogo pode começar. Compila o modem para a região do campo (`--region=`) e grava outra vez, ou põe o campo de volta na região do modem |
| O cabeçalho da consola diz **Rádio: sem modem** | `[modem] port` está vazio, ou a secção falta: secção 7 |
| O modem está **OK** mas nenhuma caixa aparece em **Procurar caixas** | A caixa e o modem não estão na mesma região ou no mesmo canal; a caixa não está adotada; a caixa continua noutro jogo (**recusou: noutro jogo**: liberta-a como no [Manual da organização](game-master.md#recover-from-problems), ou na própria caixa: [manual da Field Box](field-box.md#take-a-box-out-of-its-game)); falta uma antena ou a caixa está longe demais. [Manual da organização, Recuperar de problemas](game-master.md#recover-from-problems) |
| `Rádio: ligado` mas **fail** (a linha TX) não pára de subir | As emissões falham. Olha para a linha **DUTY**: a `0.0s` o orçamento de tempo de emissão acabou, por isso espera. Se não, confirma a antena e o estado de falha do rádio |
| **RX auth** não pára de subir | Pacotes do jogo que não decifram: uma caixa com uma chave antiga, ou outro jogo com o mesmo id por perto |
| Registo: `the radio modem's firmware cannot report boxes still in an ended game` | A imagem do modem é anterior à v0.9.0. Atualiza-a (secção 10). Até lá, tira essa caixa do jogo na própria caixa ([manual da Field Box](field-box.md#take-a-box-out-of-its-game)) |
| Telemóvel controlador: o modem não aparece na lista de **Procurar módulos** | Um cabo de dados, um adaptador OTG se o telemóvel precisar, a antena montada. Pára primeiro o controlador: o rádio escolhe-se antes de arrancar (secção 11) |
| Funcionou, e depois de reiniciar o Pi já não | O nome da porta mudou. Usa o nome `by-id` (secção 6). Confirma que o serviço está ativo no arranque: `sudo systemctl enable atalaia-controller` |

Não está na tabela? Pergunta nas [Discussions](https://github.com/vakaobr/atalaia-project/discussions) ou abre uma issue, com as linhas do registo do controlador sobre o modem, o que o ecrã diz e o teu sistema. Os pormenores do firmware do modem e do ecrã dele estão no [README do firmware](../../../firmware/esp32/README.md#usb-radio-modem-variant) (em inglês); as tramas no cabo estão em [protocol/usb-modem.md](../../../protocol/usb-modem.md).
