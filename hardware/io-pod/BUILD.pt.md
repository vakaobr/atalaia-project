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
| Amplificador e altifalante (MAX98357A), e/ou um besouro piezoelétrico passivo | tons, e os sons do modo tocados como tons; volume |
| Leitor NFC (PN532) | o registo da etiqueta de quem joga (os cartões de entrada não são passados: o telemóvel entra por código QR ou por texto) |
| Interruptor da caixa | aberta, fechada: o telemóvel comunica uma abertura à consola da organização como `node.tamper` |
| Rádio LoRa | o rádio do campo: o telemóvel fala com o controlador de campo através dele, cifrado pelo módulo com a chave do jogo |
| Medidor de bateria (MAX17048) | o nível da bateria do módulo |
| Saídas simples (opcionais, um ou dois interruptores de relé RC) | uma sirene, um estroboscópio, uma luz ou o comando de uma máquina de fumo, ligados pelo modo e pelo campo; desligados quando a ligação ao telemóvel cai ([secção 8.1](#81-saídas-simples-opcionais)) |
| Porta de expansão (opcional, a tomada M12) | os impactos de um módulo de alvo; os relés de um módulo de saídas, com a opção de compilação; ambos à vista na consola do GM ([secção 8.2](#82-porta-de-expansão-opcional)) |

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
- **Emparelhamento com código**: o pequeno OLED de 0,96" da placa fica
  apagado, exceto enquanto um telemóvel emparelha por Bluetooth: mostra um
  código de 6 dígitos, e o telemóvel pede-o, para que ninguém se meta entre o
  telemóvel e o módulo enquanto emparelham (decisões PODPK-1 a PODPK-11;
  [secção 10](#10-ligá-lo-a-um-telemóvel)). O botão **PRG** da placa,
  carregado 5 segundos, faz o módulo esquecer todos os telemóveis.
- **O registo (log)** vai para o pino de transmissão da UART0, o GPIO 43, e
  não para a porta USB-C, que leva as tramas do módulo.
- **Saídas simples** (opcionais, desde 2026-11-04; rascunho do RFC «The
  expansion port», incremento 9, EXP-26): uma sirene, um estroboscópio, uma
  luz ou o comando de uma máquina de fumo através de um interruptor de relé RC
  na porta livre do conversor de nível, como numa Field Box, no **GPIO 33**
  (uma segunda no **GPIO 1**). O módulo envia os impulsos e desliga a saída
  por si quando a ligação ao telemóvel cai ou o telemóvel deixa de falar
  ([secção 8.1](#81-saídas-simples-opcionais)). No firmware e testadas só num
  computador: nenhum módulo ligou ainda um relé verdadeiro.
- **A porta de expansão** (opcional, desde 2026-11-04; incremento 9, EXP-26):
  a tomada M12 e a placa da porta da Field Box no barramento I2C do módulo de
  E/S (GPIO 17 e 18, sem GPIO próprio), com o controlador da porta da caixa.
  Os impactos na placa de um módulo de alvo chegam ao jogo do telemóvel; os
  relés de um módulo de saídas são-lhe emprestados numa compilação que o diga;
  o módulo de E/S mantém a concessão (lease) do módulo da porta e desliga as
  suas saídas quando o telemóvel se vai ([secção 8.2](#82-porta-de-expansão-opcional)).
  No firmware e testada só num computador.

Não decidido, ou ainda sem suporte:

- **Um módulo de E/S com todas as peças e um módulo de saídas**: a descrição
  que o módulo de E/S dá de si ao telemóvel (256 bytes) tem então espaço para
  poucas saídas do módulo da porta: empresta as que cabem, as primeiras, e
  mantém as outras desligadas (com todas as peças e um out4, uma das quatro;
  com um alvo também, nenhuma). Um módulo de E/S montado para um módulo de
  saídas deixa de fora as peças que não usa (decisões EXPI9-23, EXPI9-27).
- **Energia vinda do telemóvel.** Por USB, o telemóvel alimenta a placa; com o
  interruptor principal do módulo ligado, o carregador da placa pode então
  carregar a célula do módulo a partir do telemóvel, como uma Field Box carrega
  a partir de qualquer carregador USB. Se um módulo deve fazer isso, e que
  corrente dá a porta OTG de um telemóvel, fica **por verificar na primeira
  montagem** (decisão P5J-8, para quem mantém o projeto).
- **A caixa**, e como o telemóvel e o módulo são transportados juntos (uma só
  caixa, ou duas ligadas pelo cabo): não escolhida.
- **Definições que não estão no comando pelo rádio**: o número de LED, os
  pinos, o rádio e a segurança Bluetooth vêm só da compilação do firmware; um
  módulo não tem menu de administração, por isso não tem PIN de administração
  (decisão PODC-2). As cores dos botões, o brilho do anel, o volume e o
  interruptor da caixa podem ser definidos pelo rádio
  ([secção 9, "Definições pelo rádio"](#definições-pelo-rádio)).
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
| 8 | Amplificador I2S MAX98357A e um altifalante de 4-8 ohm, 3 W; e/ou um besouro piezoelétrico passivo | 0-1 | Como na Field Box. O besouro precisa de um firmware do módulo compilado com `CONFIG_ATALAIA_BUZZER=y` e liga-se ao GPIO 45 como diz o [manual da Field Box, secção 9.7](../field-box/BUILD.pt.md#97-áudio-opcional) (decisões BZR-1 a BZR-8; ainda não montado em hardware) |
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
| Saída simples 1 (opcional) | 33 | `ATALAIA_SIMPLE_OUT_PIN` | qualquer (não está no esquema da Field Box) | entrada da porta 2 do 74AHCT125 (pino 5), 10 kohm ao GND | 3,3 V à entrada, 5 V à saída | Só numa compilação com a saída simples ([8.1](#81-saídas-simples-opcionais)) |
| Saída simples 2 (opcional) | 1 | `ATALAIA_SIMPLE_OUT2_PIN` | qualquer | entrada da porta 3 do 74AHCT125 (pino 9), 10 kohm ao GND | 3,3 V à entrada, 5 V à saída | A entrada da tensão da bateria da placa, que o módulo não usa: serve para uma saída |
| Registo (TX da UART0) | 43 | -- | qualquer | RX de um adaptador USB-UART de 3,3 V, com o seu GND | 3,3 V | Interno da placa: só enquanto lês o registo |

Trilhos, não GPIO: 3V3 (violeta) para as peças I2C e para o expansor do
teclado; GND (preto); o trilho de 5 V (laranja) para o anel, o amplificador e
os LED dos botões. A lista completa dos pinos que nunca deves ligar está na
[referência de pinos da Field Box](../field-box/BUILD.pt.md#15-referência-de-pinos) (secção 15).

Os outros pinos do ecrã de uma Field Box (GPIO 1, 3, 33) não são usados pelas
peças do módulo: os GPIO 33 e 1 levam as saídas simples opcionais; sem elas,
deixa os três sem ligação. O GPIO 0, 45 e 46 são pinos de arranque (boot
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
   e [esquema 2/2](../field-box/wiring/field-box-power.svg)): células,
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

### 8.1 Saídas simples (opcionais)

**Ainda não montadas em hardware.** Uma sirene, um estroboscópio, uma luz ou o
comando de uma máquina de fumo ligados pelo jogo no telemóvel (rascunho do RFC
«The expansion port», incremento 9, decisão EXP-26). As ligações são as da
[secção 9.10 da Field Box](../field-box/BUILD.pt.md#910-saída-simples-opcional):
um interruptor de relé RC que **abre quando o sinal para**, alimentado pela
bateria da própria carga, o sinal pela porta livre do 74AHCT125 até uma tomada
M8, com as mesmas regras: **só cargas de baixa tensão (no máximo 24 V DC),
nunca a rede elétrica, uma máquina de fumo só pela sua entrada de comando de
baixa tensão, nunca pirotecnia.** O que muda num módulo:

1. **Os pinos:** a saída 1 no **GPIO 33** (porta 2: pino 5 do GPIO 33, 10 kohm
   do pino 5 ao GND, pino 6 através de 330 ohm à tomada «OUTPUT 1»); a saída 2
   no **GPIO 1** (porta 3: pino 9, pino 8 à «OUTPUT 2»). Um módulo pode ter o
   besouro piezoelétrico no GPIO 45 **e** duas saídas.
2. **O firmware:** compila com `python tools/docker_fw.py pod --simple-out=on`
   (`on2` para duas). Um módulo não tem PIN de administração, por isso **é ao
   compilar a saída que ela fica ativa**, e o seu uso (o nome pelo qual os
   jogos a chamam: `siren`, `strobe`, `smoke`, `light`, `horn`, `out.1`) e o
   seu tempo máximo ligada são linhas em `build-pod\sdkconfig`
   ([secção 9](#9-primeira-gravação), a tabela de definições). O registo de
   arranque diz `output 1 on GPIO 33: siren, enabled, at most 30 s`.
3. **O que a liga:** o modo que corre no telemóvel (o fumo e a sirene da Bomba
   quando a bomba explode, por exemplo) e o campo (os acionadores dos
   cenários, o painel de saídas da organização), com as regras de uma caixa:
   só enquanto o jogo decorre (e até 10 s depois do fim, para uma buzina de
   fim de jogo), desligada no início, numa pausa e no fim, nunca mais tempo do
   que o seu máximo, no máximo uma mudança a cada meio segundo.
4. **Quando o telemóvel se vai, a saída desliga-se**, pelo próprio módulo: de
   imediato quando o cabo USB sai ou a ligação Bluetooth cai, e passados 1,5 s
   quando o telemóvel deixa de falar (uma app encravada mantém a ligação USB;
   enquanto uma saída está ligada, a app fala com o módulo duas vezes por
   segundo). Se o próprio módulo encravar ou ficar sem energia, os impulsos
   param em meio segundo e o interruptor abre por ter perdido o sinal.
5. **Verificações:** como o passo 7 da Field Box, no GPIO 33 (e 1): 10 kohm ao
   GND, 330 ohm da porta ao pino 4 da tomada, nada no seu pino 1. Antes do
   primeiro jogo, cada interruptor RC passa a sua verificação de bancada
   ([BRING_UP.md, passo 8b](../../firmware/esp32/docs/BRING_UP.md#step-8b-simple-output-rc-relay-switch)).
   Depois, com um telemóvel ligado e um jogo a decorrer, tira o cabo USB com a
   saída ligada: o relé abre em cerca de um segundo.

### 8.2 Porta de expansão (opcional)

**Ainda não montada em hardware.** A mesma porta de uma Field Box: a tomada
M12 e a placa da porta (buffer de ligação a quente, TVS, fusível, díodo) no
barramento I2C da placa, [guia de montagem da porta de
expansão](../expansion-port/BUILD.pt.md). Num módulo de E/S o barramento é o
do expansor do teclado, do leitor NFC e do medidor (GPIO 17 SDA, 18 SCL): nada
mais muda nas ligações. Um módulo da porta por tomada: um [módulo de
alvo](../target-addon/BUILD.pt.md) (endereço 0x58) ou um módulo de saídas
(0x5C).

1. **O firmware** procura módulos em todas as compilações do módulo de E/S
   (`CONFIG_ATALAIA_POD_PORT`): no arranque, e até 2 s depois de um ser
   ligado. O registo diz `expansion: 0x58 added: 58:target/1.0.0:hit`. Os
   relés de um módulo de saídas só são emprestados ao telemóvel numa
   compilação feita com `python tools/docker_fw.py pod --module-outputs=on`
   (`CONFIG_ATALAIA_POD_MODULE_OUTPUTS`): um módulo de E/S não tem PIN de
   administração, por isso compilá-los é o que os ativa, como às saídas
   simples. O seu tempo máximo ligados é `CONFIG_ATALAIA_POD_MODULE_MAX_ON_S`
   (30 s por omissão), nunca mais do que o do próprio módulo da porta. O
   registo diz `module 5c channel 1 lent to the phone as siren, at most 30 s`.
2. **Um alvo:** os impactos na placa chegam ao jogo no telemóvel enquanto o
   jogo decorre e o jogo armou a placa (Target Windows, a placa da Bomba...).
3. **Um módulo de saídas:** os seus relés ligam-se como as saídas simples (o
   modo, o campo, o GM; as mesmas regras). **Quando o telemóvel se vai, o
   módulo de E/S desliga-os**, logo que a ligação cai e ao fim de 1,5 s com um
   telemóvel calado; se o próprio módulo de E/S parar, o módulo de saídas
   desliga-os em 1,5 s (a sua concessão).
4. **A consola do GM** mostra as saídas e os módulos do módulo de E/S debaixo
   do telemóvel (o telemóvel passa-os), e **Desligar todas as saídas**
   chega-lhes, pelo rádio do módulo de E/S e pelo Wi-Fi do campo.
5. **Verificações:** a [secção 8 do guia da porta](../expansion-port/BUILD.pt.md#8-verificações-e-testes);
   depois, com um telemóvel ligado e um jogo a decorrer, bate na placa (um
   impacto no ecrã do telemóvel) e tira o cabo USB com um relé ligado: abre em
   cerca de um segundo.

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

**Um módulo gravado antes da v0.5** tem a tabela de partições antiga (espaços de
programa de 2 MB; a tabela da Field Box passou a espaços de 4 MB). Grava-o por USB
mais uma vez, com o mesmo comando e **sem** `erase_flash`: as definições e as chaves
ficam. O módulo só regista `WRONG PARTITION TABLE` e continua a funcionar, mas uma
atualização pelo ar não consegue mudar a tabela. Um módulo gravado pela primeira vez
a partir da v0.5 não precisa de mais nada
([guia de firmware, secção 3.3](../../docs/manuals/pt/firmware.md#33-escrever-a-imagem)).

**Definições** (linhas em `firmware\esp32\build-pod\sdkconfig`, e depois
compilar de novo; o menu Kconfig "I/O pod", listado em
firmware/esp32/README.md):

| A tua montagem | Linha em `build-pod\sdkconfig` |
| --- | --- |
| Um botão representa uma cor de equipa fixa | `CONFIG_ATALAIA_POD_BTN1_TEAM="red"` (até `BTN4`; vazio: a N.ª equipa do jogo) |
| Sem interruptor da caixa | `CONFIG_ATALAIA_POD_TAMPER_PIN=-1` (opcional: um interruptor sem ligação nunca comunica nada) |
| Interruptor aberto enquanto a tampa está fechada | `# CONFIG_ATALAIA_POD_TAMPER_OPEN_HIGH is not set` |
| Só USB, sem Bluetooth | `# CONFIG_ATALAIA_POD_BLE is not set` |
| O OLED está avariado: emparelhar sem código (Just Works) | `# CONFIG_ATALAIA_POD_BLE_PASSKEY is not set` |
| Sem botão para esquecer os telemóveis | `CONFIG_ATALAIA_POD_BOND_CLEAR_PIN=-1` (por omissão 0: o botão PRG) |
| Anel de 12 ou 16 LED | `CONFIG_ATALAIA_LED_COUNT=12` (ou 16) |
| Antena com mais de 2 dBi | `CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI=` o seu ganho, arredondado para cima |
| O uso de uma saída simples ([8.1](#81-saídas-simples-opcionais)) | `CONFIG_ATALAIA_POD_OUT1_FUNCTION="siren"` (`strobe`, `smoke`, `light`, `horn`, `out.1`; saída 2: `POD_OUT2_FUNCTION`) |
| O seu tempo máximo ligada | `CONFIG_ATALAIA_POD_OUT1_MAX_ON_S=10` (1-600 s, 30 por omissão; o módulo diz-o à app) |
| Sem porta de expansão ([8.2](#82-porta-de-expansão-opcional)) | `# CONFIG_ATALAIA_POD_PORT is not set` (opcional: sem nenhum módulo ligado custa uma sondagem a cada 250 ms) |
| Os relés de um módulo de saídas emprestados ao telemóvel | `docker_fw.py pod --module-outputs=on`, ou `CONFIG_ATALAIA_POD_MODULE_OUTPUTS=y`; o seu tempo máximo `CONFIG_ATALAIA_POD_MODULE_MAX_ON_S=60` (1-600 s, 30 por omissão) |

Deixa `CONFIG_ATALAIA_POD_BLE_ENCRYPTED` e `CONFIG_ATALAIA_POD_BLE_PASSKEY`
ligados: o primeiro impede que a chave do jogo circule numa ligação Bluetooth
sem cifra, o segundo garante que o telemóvel que emparelha é o que tens na mão
(um código no OLED do módulo). Sem OLED, o registo no GPIO 43 mostra na mesma
`pairing passkey 123456`.

### Definições pelo rádio

Quatro definições do módulo podem ser mudadas sem cabo e sem compilar de novo:
**as cores dos botões, o brilho do anel, o volume e se o interruptor da caixa
comunica**. O controlador de campo envia-as pelo rádio, a partir da consola do
GM (decisão PODC; o formato está em
[protocol/pod-config.md](../../protocol/pod-config.md), em inglês). As linhas de
`build-pod\sdkconfig` acima são os valores que o módulo tem até lhe enviarem
alguma coisa; o que é enviado fica guardado na memória flash do módulo e
prevalece sobre elas, também depois de um reinício, até ser reposto.

1. **O módulo tem de estar ligado a um telemóvel que entrou no jogo**
   ([secção 10](#10-ligá-lo-a-um-telemóvel)): o rádio do módulo é o nó do
   telemóvel no jogo e abre o comando com a chave do jogo. Um módulo sem ligação,
   ou um telemóvel fora do jogo, não pode ser alcançado.
2. Na consola do GM (a do Pi ou a do telemóvel), separador *Caixas*, painel
   *Definições dos módulos de E/S*: aparecem os telemóveis do jogo. No telemóvel
   com o módulo, marca *Definir as cores* e escolhe uma cor para cada botão
   (*a equipa do jogo* é o predefinido: o botão N é a N.ª equipa do jogo), e/ou
   o brilho do anel e o volume em percentagem, e o interruptor da caixa (*avisa
   de violação* ou *ignorado*; um interruptor que a compilação não montou
   continua desligado). Preenche só o que queres mudar. *Voltar primeiro às
   definições da compilação* deixa cair tudo o que foi enviado até então.
3. Carrega em *Enviar ao módulo*. O controlador envia pelo rádio e mostra
   *enviado (1), a aguardar*; o módulo guarda, mostra as cores novas ao
   telemóvel de imediato e di-lo através do telemóvel: a página mostra *aceite
   pelo módulo*. Se a resposta não chegar, o controlador envia de novo ao fim de
   8, 16, 32, 64 e 128 segundos e depois mostra *sem resposta*.
4. **Sem resposta** quer dizer uma destas coisas: o telemóvel não tem módulo de
   E/S (a consola não o sabe), o firmware do módulo é anterior a esta
   funcionalidade (grava um mais recente), o módulo não está ligado ou está fora
   do alcance do rádio, ou ficou sem bateria.

Só **antes de um jogo começar ou depois de terminar**; durante um jogo o painel
fica desativado. É preciso **um firmware novo do módulo** uma vez (esta
funcionalidade está no firmware); até lá o módulo continua a funcionar com as
definições da sua compilação e a consola mostra *sem resposta*.

## 10. Ligá-lo a um telemóvel

Depois segue [BRING_UP.md, "The I/O pod"](../../firmware/esp32/docs/BRING_UP.md#the-io-pod-phase-3-plan-phase-f)
(em inglês), com primeiro os passos do BRING_UP.md que se aplicam à placa
(revisão, antena, **potência de emissão: nenhum jogo antes dela**, NFC,
teclado, LED, áudio). Em resumo:

1. **USB.** Um cabo USB-C OTG do telemóvel ao módulo. Na app:
   *Dispositivo de jogo > Módulo de E/S > Procurar módulos*, abre-o, permite o
   acesso USB: "Módulo ligado por USB".
2. **Bluetooth.** Desligado do cabo: *Procurar módulos* lista
   `atalaia-pod-XXXX`; abre-o. O OLED do módulo mostra **PAIR**, os segundos
   que faltam e um código de 6 dígitos (`123 456`), com o nome do módulo por
   baixo; a janela de emparelhamento do Android pede-o: escreve os 6 dígitos
   em menos de 30 segundos. O OLED mostra **PAIRED** e a app "Módulo ligado
   por BLE". Só uma vez: o telemóvel e o módulo guardam o emparelhamento. O
   ecrã do módulo está sempre em inglês (o módulo não tem idioma).
   - **Um código errado** (ou *Cancelar*): o OLED mostra **FAILED**, a app diz
     que o código não coincidiu. Abre o módulo outra vez: um código novo.
   - **Demasiado lento**: **TOO SLOW** no OLED e uma mensagem na app. Um
     telemóvel que se liga e nunca emparelha é largado ao fim de 60 segundos.
   - **"Este módulo tem de ser emparelhado outra vez"**: o telemóvel foi
     emparelhado com este módulo antes de haver código (um firmware anterior à
     0.8), ou o módulo esqueceu os telemóveis. O OLED mostra **PAIR AGAIN**; a
     app esquece o emparelhamento antigo e abre o módulo outra vez sozinha,
     uma vez: escreve o código novo. Se o Android não deixar a app esquecê-lo,
     a app avisa: esquece `atalaia-pod-XXXX` nas definições de Bluetooth do
     Android e liga-o de novo.
   - **Esquecer todos os telemóveis**: abre a tampa e carrega no botão **PRG**
     da placa durante 5 segundos. O OLED mostra **FORGET ALL** com uma barra,
     depois **CLEARED**; um telemóvel ligado é largado. Todos os telemóveis
     emparelham de novo com código. (Abrir a tampa comunica uma violação se o
     interruptor da caixa estiver ligado: faz isto entre jogos.)
3. **Um jogo.** Um jogo de dispositivo de jogo no telemóvel com o módulo
   ligado: os seus botões são as equipas do jogo, por número, o seu anel mostra
   a equipa, o seu leitor verifica as etiquetas de quem joga, e a ligação
   rádio do telemóvel ao controlador de campo passa pelo módulo. Se a ligação
   cair durante o jogo, a app abre-a outra vez sozinha; um módulo que tenha de
   ser emparelhado outra vez é emparelhado mais uma vez, e o ecrã do jogo diz
   isso (**Este módulo tem de ser emparelhado outra vez**, escreve o código
   novo). Se não resultar, uma faixa vermelha diz **A app não conseguiu voltar
   a ligar o módulo sozinha** e porquê; uma faixa vermelha diz também quando
   respondeu outro módulo, e indica o módulo que o jogo espera. O jogo
   continua sem o módulo. Para voltar a ligar o mesmo módulo sem saíres do
   jogo, toca em **Organização**, escreve o PIN da organização e toca em
   **Ligar o módulo outra vez**: a app tenta o módulo outra vez de imediato,
   o Android pede o código do ecrã do módulo se tiver de emparelhar, e um
   módulo que recuse o emparelhamento é emparelhado mais uma vez sozinho.
   Depois de ligado, a faixa desaparece e o jogo continua com o módulo (os
   botões, as saídas e o rádio dele), sem recomeçar. Se falhar outra vez, a
   faixa vermelha volta com o motivo novo. O módulo também pode ser ligado
   no ecrã inicial do dispositivo de jogo (*Dispositivo de jogo > Módulo de
   E/S*) depois de saíres do jogo.

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
| O Android pede um código mas o OLED fica apagado | O OLED não foi encontrado no arranque (o registo diz `SSD1306 OLED not found`): o código está no registo do GPIO 43 (`pairing passkey 123456`); verifica o OLED da placa, ou compila sem código (secção 9) |
| "Este módulo tem de ser emparelhado outra vez" sempre | O Android não esqueceu o emparelhamento: esquece `atalaia-pod-XXXX` nas definições de Bluetooth e liga-o de novo |
| O telemóvel nunca mostra "Alguém abriu o módulo de E/S" | Sem interruptor no GPIO 47, ou nunca o leu fechado (a tampa não o carrega); um interruptor ligado ao contrário exige `POD_TAMPER_OPEN_HIGH` desligado |
| O módulo comunica uma abertura sozinho | O interruptor larga quando a caixa leva uma pancada: monta-o mais firme, ou usa um interruptor de alavanca |
| O botão 4 nunca regista | Está no P7 do PCF8574: o expansor tem de estar montado e ser encontrado no arranque |
| A sirene (ou o estroboscópio, o fumo) nunca liga | Uma compilação sem `--simple-out`; o seu uso em `build-pod\sdkconfig` não é o que o jogo pede (o registo de arranque mostra-o); nenhum jogo a decorrer; a bateria do próprio interruptor |
| Um módulo da porta não é encontrado (nenhum `expansion: ... added` no registo) | Como numa Field Box ([guia da porta, secção 9](../expansion-port/BUILD.pt.md#9-resolução-de-problemas)): o seu endereço, o cabo, a alimentação, o firmware |
| Os impactos do alvo nunca chegam ao jogo | O jogo não armou a placa, ou não está a decorrer; a app do telemóvel é mais antiga do que o módulo de E/S (ignora a placa) |
| Os relés de um módulo de saídas não são oferecidos ao jogo (todos ou alguns) | Uma compilação sem `--module-outputs=on`; um módulo de E/S com todas as peças: empresta as que cabem, as primeiras, e o registo nomeia as outras (`IDENT has no room for 3 output(s), not lent (off, refused): strobe, smoke, out.4`; [secção 2](#2-o-que-está-decidido-e-o-que-não-está)) |
| A saída desliga-se sozinha ao fim de um ou dois segundos | O telemóvel deixou de falar com o módulo (a app em segundo plano ou terminada: vê as definições de bateria da app) ou a ligação caiu: o módulo desliga-a de propósito |
| Algo quente, um cheiro, fumo | Desliga o telemóvel, desliga o interruptor, tira o fusível, tira as células para um saco à prova de fogo |

Se encontrares uma avaria que não está aqui, ou um passo errado, abre uma
issue (fotografias são bem-vindas): este guia é corrigido a partir das
primeiras montagens.

---

Licença: este guia é CC-BY-SA-4.0; os projetos de hardware a que se refere são
CERN-OHL-S-2.0 ([LICENSING.md](../../LICENSING.md)).
