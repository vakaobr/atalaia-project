<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Guia de montagem do módulo de E/S

Em inglês: [I/O pod build guide](BUILD.md). O guia de firmware: [firmware.md](../../docs/manuals/pt/firmware.md).

De um saco de peças a um módulo de E/S com o firmware gravado: uma caixa que
dá a um telemóvel ou tablet Android, com um dispositivo de jogo da Atalaia, o
que ao telemóvel falta: botões de equipa grandes, um teclado, um anel de
luzes, som, um leitor NFC, um interruptor da caixa e um rádio LoRa. O telemóvel
corre o modo de jogo; o módulo são as suas mãos e o seu rádio, por um cabo USB
ou por Bluetooth LE. Escrito para quem, num clube, sabe soldar pinos e fios e
usar um multímetro, como o
[manual de montagem da Field Box](../field-box/BUILD.pt.md), que este guia
segue e a que recorre em todos os passos que as duas montagens partilham.

> **Estado: ainda não montado.** Nenhum módulo foi montado a partir deste guia,
> e o firmware do módulo **ainda não foi testado numa placa a sério**: é
> compilado e testado num computador, contra a app e o controlador de campo
> (fase 3 do plano, fase F). O módulo usa os pinos da Field Box, verificados
> automaticamente contra os valores por omissão do firmware
> (`python3 tools/check_wiring.py`). Todos os passos físicos, as ligações a um
> telemóvel a sério, o emparelhamento e o rádio no ar estão **por testar**
> ([BRING_UP.md, "The I/O pod"](../../firmware/esp32/docs/BRING_UP.md#the-io-pod-phase-3-plan-phase-f)
> (em inglês) lista as verificações que faltam). Os passos marcados
> **Verifica na primeira montagem** são perguntas em aberto; diz-nos o que
> encontrares, numa issue. As fotografias entram depois da primeira montagem
> (fase HW2 do plano); este guia nunca usa fotografias de maquetas nem geradas.

## Índice

1. [O que estás a montar](#1-o-que-estás-a-montar)
2. [O que está decidido e o que não está](#2-o-que-está-decidido-e-o-que-não-está)
3. [Peças](#3-peças)
4. [Ferramentas e segurança](#4-ferramentas-e-segurança)
5. [Pinos](#5-pinos)
6. [Caixa e interruptor da caixa](#6-caixa-e-interruptor-da-caixa)
7. [Revisão da placa, antenas e energia](#7-revisão-da-placa-antenas-e-energia)
8. [Ligações, passo a passo](#8-ligações-passo-a-passo)
9. [Primeira gravação](#9-primeira-gravação)
10. [Ligá-lo a um telemóvel](#10-ligá-lo-a-um-telemóvel)
11. [Resolução de problemas](#11-resolução-de-problemas)

## 1. O que estás a montar

O hardware da Field Box **sem o ecrã a cores**: a mesma placa ESP32-S3
(Heltec WiFi LoRa 32 V4, revisão V4.2 ou V4.3), até quatro botões de equipa,
um teclado através do expansor PCF8574, um anel de luzes, um leitor NFC, um
amplificador e altifalante, um medidor de bateria, uma célula de iões de
lítio, mais um interruptor que diz quando a caixa é aberta. Todas as peças,
menos a placa, são opcionais: o módulo diz ao telemóvel o que tem (o seu
IDENT) e o telemóvel usa só isso. Custo aproximado: cerca de 35 € pelas peças
do módulo, a preços do mercado de amadores
([especificação de conceção](../../docs/design-spec.md), secção 6); não é um
orçamento, e não foi confrontado com uma montagem a sério.

```
phone or tablet  <-- USB-C OTG cable, or Bluetooth LE -->  pod board  --> LoRa radio
(runs the mode)                                              |
                                  team buttons, keypad (PCF8574), LED ring,
                                  NFC reader, amplifier, battery gauge,
                                  enclosure switch
```

O que o módulo empresta, segundo o firmware do módulo
([firmware/esp32/README.md, "The I/O pod"](../../firmware/esp32/README.md#the-io-pod-phase-3-plan-phase-f)):

| Peça | O que o telemóvel recebe |
| --- | --- |
| Botões de equipa 1-4 | carregar, manter (a cada 250 ms), largar. O botão N é a N.ª equipa do jogo, como numa Field Box, a não ser que o firmware defina uma cor |
| Teclado (3x4, através de um PCF8574) | cada tecla |
| Anel de luzes (WS2812B) | encher com a cor de uma equipa, uma só cor, apagar, brilho, uma barra de progresso |
| Amplificador e altifalante (MAX98357A) | tons, e os sons do modo tocados como tons; volume |
| Leitor NFC (PN532) | o registo da etiqueta de quem joga (os cartões de entrada não são passados: o telemóvel entra por código QR ou por texto) |
| Interruptor da caixa | aberta, fechada: o telemóvel comunica uma abertura à consola da organização como `node.tamper` |
| Rádio LoRa | o rádio do campo: o telemóvel fala com o controlador de campo através dele, cifrado pelo módulo com a chave do jogo |
| Medidor de bateria (MAX17048) | o nível da bateria do módulo |

## 2. O que está decidido e o que não está

Decidido (no firmware e nos documentos de conceção):

- **O firmware do módulo** é a terceira imagem do projeto de firmware da Field
  Box (`python tools/docker_fw.py pod`, ADR-P3-3), com **os pinos da Field
  Box** para todas as peças que partilha ([secção 5](#5-pinos)). Não tem Lua,
  ecrãs, predefinições nem Wi-Fi.
- **O interruptor da caixa** no GPIO 47 (o relógio do ecrã da Field Box; um
  módulo não tem ecrã), ao GND, fechado enquanto a tampa está fechada
  (decisão PF8).
- **Duas ligações ao telemóvel ao mesmo tempo**: USB (a porta USB-C da placa,
  que o telemóvel vê como um dispositivo série) e Bluetooth LE
  (`atalaia-pod-XXXX`, um telemóvel de cada vez, emparelhado e cifrado;
  decisões PF3, PF4).
- **O registo (log)** vai para o pino de transmissão da UART0, o GPIO 43, e
  não para a porta USB-C, que leva as tramas do módulo.

Não decidido, ou ainda sem suporte:

- **A sirene** da especificação de conceção: o som do módulo é o amplificador e
  o altifalante. Uma sirene separada, um relé ou um estroboscópio (a
  capacidade `output` da especificação) não estão no firmware do módulo
  (decisão P5J-7).
- **Energia vinda do telemóvel.** Por USB, o telemóvel alimenta a placa; com o
  interruptor principal do módulo ligado, o carregador da placa pode então
  carregar a célula do módulo a partir do telemóvel, como uma Field Box carrega
  a partir de qualquer carregador USB. Se um módulo deve fazer isso, e que
  corrente dá a porta OTG de um telemóvel, fica **por verificar na primeira
  montagem** (decisão P5J-8, para quem mantém o projeto).
- **A caixa**, e como o telemóvel e o módulo são transportados juntos (uma só
  caixa, ou duas ligadas pelo cabo): não escolhida.
- **Definições pela ligação** (cores dos botões, número de LED...): o módulo
  recebe-as só da compilação do firmware (decisão PF15).
- **Um esquema de ligações próprio**: as ligações do módulo são as da Field Box
  sem o ecrã ([secção 8](#8-ligações-passo-a-passo)); pode surgir um com a
  primeira montagem (P5J-12).

## 3. Peças

As peças da Field Box ([manual, secção 2](../field-box/BUILD.pt.md), onde estão
as armadilhas de cada uma), menos o ecrã e a sua janela, mais:

| # | Peça | Qtd. | O que verificar |
| --- | --- | --- | --- |
| 1 | Heltec WiFi LoRa 32 V4 (V4.2 ou V4.3), placa nua, 863-928 MHz | 1 | Como na Field Box |
| 2 | Antena de 868 MHz, 2 dBi ou menos | 1 | Como na Field Box |
| 3 | Antena FPC de 2,4 GHz com cabo IPEX 1.0 | 1 | **Obrigatória para o Bluetooth** (o módulo não tem Wi-Fi) |
| 4 | Botões arcade de 60 mm, LED de 5 V | 0-4 | Como na Field Box; o botão 4 precisa do expansor do teclado |
| 5 | Teclado de membrana 3x4 e um módulo PCF8574 (ou PCF8574A) | 0-1 | Como na Field Box: o PCF8574 alimentado a 3V3; não uma "placa LCD I2C" |
| 6 | Anel de LED WS2812B, 5 V, com o conversor de nível 74AHCT125, o seu suporte, 100 nF, 330 ohm e 1000 µF | 0-1 | Como na Field Box |
| 7 | Módulo NFC PN532 (I2C) | 0-1 | Como na Field Box |
| 8 | Amplificador I2S MAX98357A e um altifalante de 4-8 ohm, 3 W | 0-1 | Como na Field Box; o único som do módulo |
| 9 | Medidor de bateria MAX17048 | 1 | Recomendado: o telemóvel mostra o nível da bateria do módulo |
| 10 | Células 18650 protegidas (uma, ou duas num suporte em **paralelo**) ou um pack 1S com BMS | 1S | **Uma só célula, em série** |
| 11 | Conversor elevador (boost) de 5 V (saída de 5 V, 2,5 A ou mais), porta-fusível e fusível de 5 A, díodo Schottky (p. ex. 1N5822), interruptor principal tapado, conectores de alavanca | 1 de cada | Como na Field Box ([manual, secção 7](../field-box/BUILD.pt.md)) |
| 12 | Microinterruptor (de ação rápida, de alavanca ou de êmbolo) para o interruptor da caixa | 1 | Normalmente aberto ou com terminais COM/NO/NC; a tampa tem de o manter **fechado** quando está fechada |
| 13 | Extensão USB-C de painel com tampa, USB 2.0 **de dados** | 1 | O cabo do telemóvel liga-se aqui; uma extensão "só de carga" estraga a ligação USB |
| 14 | Cabo ou adaptador USB-C OTG para o telemóvel | 1 | O telemóvel tem de suportar USB host (OTG) |
| 15 | Adaptador USB-UART de 3,3 V | 1 (para a bancada) | Só para ler o registo do módulo no GPIO 43 enquanto o montas; lógica de **3,3 V**, nunca de 5 V |
| 16 | Caixa IP65, de cor viva, não metálica; bucins, respiro; placa perfurada; etiquetas "GAME PROP" | 1 conjunto | [Secção 6](#6-caixa-e-interruptor-da-caixa) |

## 4. Ferramentas e segurança

As ferramentas são as da Field Box ([manual, secção 3](../field-box/BUILD.pt.md)).
Lê as suas [regras de segurança](../field-box/BUILD.pt.md#4-regras-de-segurança) (secção 4); aplicam-se todas.
Para um módulo em particular:

1. **Nunca alimentes a placa sem a antena LoRa ligada**, nem sequer pelo cabo do
   telemóvel: transmitir para uma porta de antena aberta pode destruir o
   amplificador de entrada do rádio.
2. **Uma só célula de iões de lítio, em série (1S)**; células protegidas, um
   fusível junto à célula, polaridade verificada com o multímetro antes de cada
   ligação, carregar só com vigilância, nunca numa caixa fechada, só entre
   cerca de 0 e 45 °C; células fora enquanto trabalhas.
3. **Só sinais de 3,3 V** para a placa: os módulos I2C puxam para 3,3 V, o anel
   é comandado através do conversor de nível, e o adaptador USB-UART é de 3,3 V.
4. **Nunca ligues o GPIO 5 ou 46, nem o GPIO 34 ou 38-42**, nem nada ao GPIO 43
   a não ser a linha de receção do adaptador enquanto lês o registo.
5. **Nenhum jogo antes da verificação da potência de emissão** (BRING_UP.md,
   passo 10, e depois os passos próprios do módulo).
6. **Um dispositivo de jogo, com um telemóvel lá dentro.** Cor viva, etiquetas
   "GAME PROP", nada que pareça um explosivo. O ecrã do telemóvel e os botões
   do módulo vão apanhar BB e bolas de paintball: atrás de uma cobertura
   transparente de policarbonato, nunca de vidro, numa capa robusta; o cabo
   fixo, para que ninguém o consiga arrancar do telemóvel ou da caixa.

## 5. Pinos

Os pinos da Field Box, para as peças que um módulo tem, e o interruptor da
caixa. São os valores por omissão em
[`firmware/esp32/main/Kconfig.projbuild`](../../firmware/esp32/main/Kconfig.projbuild),
a referência se os dois alguma vez divergirem; `python3 tools/check_wiring.py`
falha se esta tabela divergir.

| Função | GPIO | Símbolo Kconfig | Cor do fio | Liga a | Nível | Notas |
| --- | --- | --- | --- | --- | --- | --- |
| Botão 1 | 4 | `ATALAIA_BTN1_PIN` | verde | microinterruptor NO; COM ao GND | 3,3 V | Ativo em baixo, pull-up interna |
| Botão 2 | 48 | `ATALAIA_BTN2_PIN` | verde | microinterruptor NO; COM ao GND | 3,3 V | |
| Botão 3 | 44 | `ATALAIA_BTN3_PIN` | verde | microinterruptor NO; COM ao GND | 3,3 V | Linha de receção da UART0: o TX do adaptador do registo tem de ficar fora dela |
| Botão 4 | PCF8574 P7 | `ATALAIA_KP_P7_BUTTON` | verde | microinterruptor NO; COM ao GND | 3,3 V | No pino livre do expansor do teclado; só funciona com o expansor montado |
| Teclado | I2C | -- | castanho, vermelho, laranja, amarelo (linhas R1-R4), verde, azul, violeta (colunas C1-C3) | PCF8574 P0-P3 e P4-P6 | 3,3 V | PCF8574 em 0x20 (um PCF8574A em 0x38 também é encontrado) |
| Dados do anel de luzes | 35 | `ATALAIA_LED_PIN` | branco | hub "LED data in", depois o 74AHCT125 e 330 ohm até ao DIN do anel | 3,3 V à entrada, 5 V à saída | |
| I2C SDA | 17 | `ATALAIA_NFC_SDA_PIN` | azul | trilho SDA do hub: PCF8574, PN532 (0x24), MAX17048 (0x36) | 3,3 V | O barramento da placa (o seu OLED não é usado por um módulo) |
| I2C SCL | 18 | `ATALAIA_NFC_SCL_PIN` | amarelo | trilho SCL do hub | 3,3 V | |
| I2S BCLK | 6 | `ATALAIA_AUDIO_BCLK_PIN` | cinzento | BCLK do amplificador | 3,3 V | MAX98357A |
| I2S LRCLK | 15 | `ATALAIA_AUDIO_LRCLK_PIN` | rosa | LRC do amplificador | 3,3 V | |
| I2S DOUT | 16 | `ATALAIA_AUDIO_DOUT_PIN` | castanho | DIN do amplificador | 3,3 V | |
| Interruptor da caixa | 47 | `ATALAIA_POD_TAMPER_PIN` | qualquer (não está no esquema da Field Box) | COM do microinterruptor ao GND, NO ao pino | 3,3 V, pull-up interna | Fechado enquanto a tampa está fechada |
| Registo (TX da UART0) | 43 | -- | qualquer | RX de um adaptador USB-UART de 3,3 V, com o seu GND | 3,3 V | Interno da placa: só enquanto lês o registo |

Trilhos, não GPIO: 3V3 (violeta) para as peças I2C e para o expansor do
teclado; GND (preto); o trilho de 5 V (laranja) para o anel, o amplificador e
os LED dos botões. A lista completa dos pinos que nunca deves ligar está na
[referência de pinos da Field Box](../field-box/BUILD.pt.md#15-referência-de-pinos) (secção 15).

Os outros pinos do ecrã de uma Field Box (GPIO 1, 3, 33) não são usados pelo
módulo: deixa-os sem ligação. O GPIO 0, 45 e 46 são pinos de arranque (boot
strap); os pinos internos da placa estão listados no
[mapa de pinos da Field Box](../field-box/README.md#pin-assignments-default-kconfig----heltec-v43).

## 6. Caixa e interruptor da caixa

<!-- PHOTO: io-pod-enclosure.jpg | the pod's enclosure, with the enclosure switch and the lid's tab that presses it -->
> **Fotografia a juntar depois da primeira montagem:** a caixa, com o
> interruptor da caixa e a parte da tampa que o carrega.

Nenhuma caixa foi escolhida. Prepara-a como a da Field Box
([manual, secção 5](../field-box/BUILD.pt.md)): de plástico, nunca de metal (o
rádio e o Bluetooth têm de sair), IP65, de cor viva, botões na tampa, o
interruptor principal embutido ou tapado, um respiro, a tomada USB-C de painel
onde o cabo do telemóvel a alcance, todos os furos que não usares selados.

**O interruptor da caixa.** Monta um microinterruptor lá dentro de modo que a
tampa fechada o carregue, e liga-o entre o **GPIO 47** e o **GND**: fechado
(carregado) enquanto a tampa está fechada, aberto quando a tampa é levantada. O
firmware só o arma depois de o ter lido fechado uma vez, por isso um módulo
montado sem interruptor nunca comunica uma abertura. Um interruptor ligado ao
contrário (aberto enquanto fechado) exige desligar
`CONFIG_ATALAIA_POD_TAMPER_OPEN_HIGH`.

**Verifica na primeira montagem:** que a tampa carrega o interruptor sem falhas
em todos os fechos, e que ele não larga quando a caixa leva uma pancada; o
alcance do Bluetooth através da parede.

## 7. Revisão da placa, antenas e energia

<!-- PHOTO: io-pod-board-power.jpg | the board with both antennas fitted and labelled, and the power path as built -->
> **Fotografia a juntar depois da primeira montagem:** a placa com as duas
> antenas montadas e etiquetadas, e o caminho da energia tal como ficou.

Exatamente como na Field Box:

1. **Revisão da placa** ([manual, secção 6](../field-box/BUILD.pt.md)):
   **KCT8103L** junto ao conector LoRa é uma V4.3 (a omissão), **GC1109** uma
   V4.2. Escreve-a na placa traseira; o firmware do módulo tem de ser
   compilado para ela.
2. **Antenas antes de qualquer energia**, as duas etiquetadas: LoRa (868 MHz,
   2 dBi ou menos, ou define o ganho de antena no firmware) e a antena FPC de
   2,4 GHz (Bluetooth).
3. **Caminho da energia** ([manual, secção 7](../field-box/BUILD.pt.md)
   e [esquema 2/2](../field-box/wiring/field-box-power.svg)): célula(s),
   fusível, díodo Schottky, interruptor principal, derivação BAT+; o conversor
   elevador regulado sozinho para 5,0-5,2 V primeiro; depois as cargas de 5 V
   (anel, amplificador, LED dos botões, conversor de nível); a entrada de
   medição de bateria do medidor em BAT+; o cabo de bateria da placa por
   último, depois de verificada a polaridade.

**Verifica na primeira montagem:** o que a placa consome da porta USB-C OTG do
telemóvel com o interruptor desligado e ligado (a carregar), a autonomia de um
jogo de 2 horas por Bluetooth (BRING_UP.md, "The I/O pod", passo 10).

## 8. Ligações, passo a passo

<!-- PHOTO: io-pod-inside.jpg | the inside of the finished pod, with the wiring routed -->
> **Fotografia a juntar depois da primeira montagem:** o interior do módulo
> acabado, com as ligações encaminhadas.

Célula fora, fusível fora, interruptor desligado. Segue as
[ligações passo a passo](../field-box/BUILD.pt.md#9-ligações-passo-a-passo) da Field Box (secção 9) e o seu
[esquema de sinais](../field-box/wiring/field-box-wiring.svg), **deixando de
fora o ecrã** (secção 9.4 do manual) e os seus fios para os GPIO 1, 3, 33 e 47,
e depois junta o interruptor da caixa:

1. **Placa de interligação** ([manual, secção 8](../field-box/BUILD.pt.md)):
   trilhos 3V3, GND, SDA, SCL e 5V, e o 74AHCT125. Sem o ecrã, os seus pinos
   3V3 e GND para o ecrã ficam livres.
2. **Placa e trilhos**: 3V3, GND, GPIO 17 (SDA) e GPIO 18 (SCL) ao hub.
3. **Módulos I2C** que montares: PCF8574 (jumpers de endereço todos ao GND:
   0x20), PN532 (interruptores de modo em I2C), MAX17048, cada um com 3V3, GND,
   SDA e SCL do hub, e cada um verificado quanto a puxar SDA e SCL para 3,3 V
   ou menos antes de entrar no barramento.
4. **Teclado** no PCF8574: linhas R1-R4 em P0-P3, colunas C1-C3 em P4-P6,
   identificadas primeiro com o multímetro.
5. **Anel de luzes**: condensador junto ao anel, DIN ao "LED data out" do hub,
   5 V e GND às derivações de 5 V, GPIO 35 ao "LED data in".
6. **Botões de equipa**: NO aos GPIO 4, 48 e 44, e o botão 4 ao P7 do PCF8574;
   COM ao GND.
7. **Amplificador**: BCLK ao GPIO 6, LRC ao GPIO 15, DIN ao GPIO 16; VIN e GND
   aos 5 V; os fios do altifalante nunca ao GND.
8. **Interruptor da caixa**: COM a um pino GND do hub, NO ao **GPIO 47**
   ([secção 6](#6-caixa-e-interruptor-da-caixa)). Verifica com o multímetro: o
   fio do interruptor apita para o GND com a tampa fechada, e não com ela
   aberta.
9. **USB.** A extensão USB-C de painel à porta USB-C da placa.
10. **Cabo de bateria da placa**, depois da verificação da polaridade
    ([manual, 9.8](../field-box/BUILD.pt.md)).

Depois, a [inspeção final](../field-box/BUILD.pt.md) da Field Box (9.9), menos a
linha do ecrã.

## 9. Primeira gravação

O firmware do módulo grava-se a partir do teu computador, como o da Field Box
([manual, secção 11](../field-box/BUILD.pt.md)). **O mais fácil:
transfere `atalaia-io-pod-<version>-usb.zip` da
[página de Releases do GitHub](https://github.com/vakaobr/atalaia-project/releases)** (pré-alfa, não testado num campo; V4.3, EU868; confere
o `SHA256SUMS`), descomprime-o e grava a partir dessa pasta como dizem os passos
2 em diante. Ou compila-o em Docker, com duas diferenças da Field Box: o
comando de compilação e a pasta de compilação.

1. **Compilar** (acrescenta `--region=as923-tw` para Taiwan: o módulo, o modem,
   as caixas e o controlador têm de partilhar uma região):

   ```
   python tools\docker_fw.py pod
   ```

   Termina com `I/O pod firmware: firmware/esp32/build-pod/atalaia_esp32.bin`.
   É compilado por omissão para uma placa **V4.3**. O ficheiro de definições
   do módulo é `firmware\esp32\build-pod\sdkconfig` (não o
   `firmware\esp32\sdkconfig` da Field Box): para uma **V4.2**, muda as suas
   duas linhas de placa como diz o [manual, secção 11](../field-box/BUILD.pt.md),
   passo 2, e compila de novo. A compilação cria um ficheiro de definições novo
   sempre que `sdkconfig.defaults` ou `sdkconfig.pod` mudam, por isso anota o
   que mudaste.
2. **Gravar** com o esptool como dizem os passos 3-6 do manual, a partir de
   `firmware\esp32\build-pod` em vez de `firmware\esp32\build`:

   ```
   cd firmware\esp32\build-pod
   %FLASH% -m esptool --chip esp32s3 -p COM5 -b 921600 write_flash "@flash_args"
   cd ..\..\..
   ```
   Reinicia-o com `%FLASH% -m esptool --chip esp32s3 -p COM5 --after hard_reset chip_id`.
   O [guia de firmware](../../docs/manuals/pt/firmware.md#10-as-variantes-do-módulo-de-es) (secção 10, os
   módulos de E/S) tem os passos para macOS e Linux e o que mais é diferente
   num módulo.
3. **Lê o registo** no GPIO 43 com o adaptador USB-UART de 3,3 V (o seu RX ao
   GPIO 43, o seu GND ao GND, o seu TX sem ligação), a 115200 baud. Espera
   `Atalaia I/O pod`, `Vext on`, uma linha por cada peça em falta, as linhas do
   rádio, `advertising as atalaia-pod-XXXX` e a lista das capacidades que
   empresta.

**Definições** (linhas em `firmware\esp32\build-pod\sdkconfig`, e depois
compilar de novo; o menu Kconfig "I/O pod", listado em
firmware/esp32/README.md):

| A tua montagem | Linha em `build-pod\sdkconfig` |
| --- | --- |
| Um botão representa uma cor de equipa fixa | `CONFIG_ATALAIA_POD_BTN1_TEAM="red"` (até `BTN4`; vazio: a N.ª equipa do jogo) |
| Sem interruptor da caixa | `CONFIG_ATALAIA_POD_TAMPER_PIN=-1` (opcional: um interruptor sem ligação nunca comunica nada) |
| Interruptor aberto enquanto a tampa está fechada | `# CONFIG_ATALAIA_POD_TAMPER_OPEN_HIGH is not set` |
| Só USB, sem Bluetooth | `# CONFIG_ATALAIA_POD_BLE is not set` |
| Anel de 12 ou 16 LED | `CONFIG_ATALAIA_LED_COUNT=12` (ou 16) |
| Antena com mais de 2 dBi | `CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI=` o seu ganho, arredondado para cima |

Deixa `CONFIG_ATALAIA_POD_BLE_ENCRYPTED` ligado: impede que a chave do jogo
circule numa ligação Bluetooth sem cifra.

## 10. Ligá-lo a um telemóvel

Depois segue [BRING_UP.md, "The I/O pod"](../../firmware/esp32/docs/BRING_UP.md#the-io-pod-phase-3-plan-phase-f)
(em inglês), com primeiro os passos do BRING_UP.md que se aplicam à placa
(revisão, antena, **potência de emissão: nenhum jogo antes dela**, NFC,
teclado, LED, áudio). Em resumo:

1. **USB.** Um cabo USB-C OTG do telemóvel ao módulo. Na app:
   *Dispositivo de jogo > Módulo de E/S > Procurar módulos*, abre-o, permite o
   acesso USB: "Módulo ligado por USB".
2. **Bluetooth.** Desligado do cabo: *Procurar módulos* lista
   `atalaia-pod-XXXX`; abre-o e confirma uma vez a pergunta de emparelhamento
   do Android: "Módulo ligado por BLE".
3. **Um jogo.** Um jogo de dispositivo de jogo no telemóvel com o módulo
   ligado: os seus botões são as equipas do jogo, por número, o seu anel mostra
   a equipa, o seu leitor verifica as etiquetas de quem joga, e a ligação
   rádio do telemóvel ao controlador de campo passa pelo módulo.

## 11. Resolução de problemas

O [manual da Field Box, secção 13](../field-box/BUILD.pt.md) cobre a placa, os
módulos I2C, o teclado, o anel, os botões, o amplificador e a energia. Para um
módulo em particular:

| Sintoma | Causa provável e correção |
| --- | --- |
| Nenhum registo | O registo está no GPIO 43 (UART0), não na porta USB-C: o RX do adaptador ao GPIO 43, GND ao GND, 115200 baud |
| O telemóvel não encontra o módulo por USB | Um cabo ou uma extensão de painel só de carga; o telemóvel não tem USB host (OTG) |
| Abrir a porta USB reinicia o módulo | A app põe DTR e RTS ao mesmo tempo; outra app série pode não o fazer: usa a app da Atalaia |
| `atalaia-pod-XXXX` não aparece na lista | A antena de 2,4 GHz em falta ou no conector errado; outro telemóvel está ligado (um de cada vez); Bluetooth desligado na compilação |
| O telemóvel nunca mostra "Alguém abriu o módulo de E/S" | Sem interruptor no GPIO 47, ou nunca o leu fechado (a tampa não o carrega); um interruptor ligado ao contrário exige `POD_TAMPER_OPEN_HIGH` desligado |
| O módulo comunica uma abertura sozinho | O interruptor larga quando a caixa leva uma pancada: monta-o mais firme, ou usa um interruptor de alavanca |
| O botão 4 nunca regista | Está no P7 do PCF8574: o expansor tem de estar montado e ser encontrado no arranque |
| Algo quente, um cheiro, fumo | Desliga o telemóvel, desliga o interruptor, tira o fusível, tira as células para um saco à prova de fogo |

Se encontrares uma avaria que não está aqui, ou um passo errado, abre uma
issue (fotografias são bem-vindas): este guia é corrigido a partir das
primeiras montagens.

---

Licença: este guia é CC-BY-SA-4.0; os projetos de hardware a que se refere são
CERN-OHL-S-2.0 ([LICENSING.md](../../LICENSING.md)).
