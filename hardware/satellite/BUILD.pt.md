<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Guia de montagem da caixa Satélite

Em inglês: [Satellite build guide](BUILD.md). O guia de firmware: [firmware.md](../../docs/manuals/pt/firmware.md).

De um saco de peças a uma caixa Satélite com o firmware gravado: uma caixa
secundária pequena, com dois botões de equipa e um anel de luzes, para os
satélites de *Mestre e Satélites*, uma baliza ou um segundo ponto de captura.
Escrito para quem, num clube, sabe soldar pinos e fios e usar um multímetro,
como o [manual de montagem da Field Box](../field-box/BUILD.pt.md), que este guia
segue e a que recorre em todos os passos que as duas montagens partilham.

> **Estado: ainda não montada.** Nenhuma caixa Satélite foi montada a partir
> deste guia. O mesmo firmware já correu em placas Heltec V4.3 nuas, numa
> bancada, com dois botões e o OLED da própria placa (convidadas para jogos
> pelo rádio, adotadas por USB e por código). **Ainda não testado numa placa a
> sério:** o anel de luzes, o medidor de bateria, o amplificador, o caminho da
> energia e a caixa. Corre o firmware da própria Field Box com menos peças
> montadas, por isso todos os pinos abaixo são pinos da Field Box, verificados
> automaticamente contra os valores por omissão do firmware
> (`python3 tools/check_wiring.py`, ver
> [Regenerar os esquemas](../field-box/BUILD.pt.md), secção 14).
> Todos os passos físicos (caixa, caminho da energia, corrente, autonomia,
> alcance do rádio) estão **por testar**. Os passos marcados **Verificar na
> primeira montagem** são perguntas em aberto; diz-nos o que encontrares, numa
> issue. As fotografias entram depois da primeira montagem (fase HW2 do plano);
> este guia nunca usa fotografias de maquetas nem geradas.

## Índice

1. [O que estás a montar](#1-o-que-estás-a-montar)
2. [O que está decidido e o que não está](#2-o-que-está-decidido-e-o-que-não-está)
3. [Peças](#3-peças)
4. [Ferramentas e segurança](#4-ferramentas-e-segurança)
5. [Pinos](#5-pinos)
6. [Caixa](#6-caixa)
7. [Revisão da placa e antenas](#7-revisão-da-placa-e-antenas)
8. [Energia](#8-energia)
9. [Ligações, passo a passo](#9-ligações-passo-a-passo)
10. [Primeiro arranque e primeira gravação](#10-primeiro-arranque-e-primeira-gravação)
11. [Preparar para o campo](#11-preparar-para-o-campo)
12. [Resolução de problemas](#12-resolução-de-problemas)

## 1. O que estás a montar

Uma caixa à prova de intempéries, mais pequena do que uma Field Box, com dois
botões de equipa grandes (um terceiro é possível), um anel de luzes que mostra
que equipa a ocupa, e o pequeno ecrã da própria placa para o seu estado, em
torno da mesma placa ESP32-S3 da Field Box (Heltec WiFi LoRa 32 V4, revisão
V4.2 ou V4.3). Funciona com uma célula de iões de lítio 18650 protegida e
carrega por USB-C. Custo aproximado: 30-40 € a preços do mercado de amadores
([especificação de conceção](../../docs/design-spec.md), secção 6); não é um
orçamento, e não foi confrontado com uma montagem a sério.

```
18650 (1S) --fuse--+--switch--+-- board battery socket --> main board --> 3.3 V rail
              diode-+          +-- MAX17048 (battery sense)      |           |
                               +-- 5 V boost --> LED ring,       |     MAX17048 logic
                                                 button LEDs     +--> GPIOs: buttons, LED data
```

**Não tem ecrã a cores, teclado, leitor NFC nem altifalante** (pode juntar-se um
altifalante, [secção 3](#3-peças)). Por isso:

- joga os jogos que um **controlador de campo** dirige: é convidada para um jogo
  pelo rádio e recebe o seu papel (`satellite`, `master`, ou uma zona de
  qualquer modo que precise só de botões de equipa) do controlador. Sem
  teclado, não pode escolher um jogo sozinha;
- mostra o seu estado no anel de luzes (a cor da equipa que a ocupa) e no
  pequeno ecrã OLED da placa (o jogo, o estado da caixa, um código de
  emparelhamento);
- é adotada por um campo por cabo USB ou pelo seu código de emparelhamento pelo
  rádio (sem cartão de campo: não tem leitor NFC).

## 2. O que está decidido e o que não está

Decidido (no firmware e nos documentos de conceção):

- **Um só firmware.** Uma caixa Satélite corre a imagem da Field Box
  (`python tools/docker_fw.py build`). Não há firmware de satélite à parte: o
  papel de uma caixa num jogo vem do controlador quando ela entra
  (`modes/master_satellites/mode.yaml`: os papéis `master` e `satellite`
  precisam só de `team_input`, que dois botões de equipa dão). O firmware
  comunica cada peça em falta uma vez no arranque e continua sem ela.
- **Os mesmos pinos da Field Box** para as peças que tem ([secção 5](#5-pinos)).
- **Uma célula de iões de lítio (1S)** com a proteção da Field Box: fusível,
  díodo Schottky, interruptor principal, conversor elevador (boost) de 5 V para
  o anel de luzes.

Não decidido, ou ainda sem suporte:

- **O besouro piezo (buzzer)** que a especificação de conceção lista para o
  Satélite **não tem suporte do firmware**: o firmware só faz som através do
  amplificador I2S MAX98357A. Monta o amplificador e um altifalante pequeno se
  quiseres som, ou constrói-a silenciosa. Um controlador de piezo seria uma
  alteração do firmware (decisão P5J-4, para quem mantém o projeto).
- **O tamanho e a disposição da caixa**: nenhuma caixa de Satélite foi
  escolhida; a [secção 6](#6-caixa) diz o que ela tem de fazer.
- **Autonomia com uma célula**: não medida.
- **Um esquema de ligações próprio**: as ligações do Satélite são um
  subconjunto dos esquemas da Field Box ([secção 9](#9-ligações-passo-a-passo));
  pode surgir um esquema próprio com a primeira montagem (P5J-12).

## 3. Peças

Descrições genéricas e as especificações a verificar; o [manual da Field Box,
secção 2](../field-box/BUILD.pt.md) tem as mesmas peças com as suas armadilhas.
Nenhuma loja é recomendada.

| # | Peça | Qtd. | O que verificar |
| --- | --- | --- | --- |
| 1 | Heltec WiFi LoRa 32 V4 (V4.2 ou V4.3), placa nua, 863-928 MHz | 1 | A versão de 863-928 MHz, não a de 433/470 MHz. O seu OLED de 0,96" é o único ecrã do Satélite |
| 2 | Antena de 868 MHz, 2 dBi ou menos | 1 | A antena do kit da placa funciona atrás de uma parede de plástico; para mais alcance, uma tomada SMA de painel e um cabo adaptador (pigtail), como na Field Box. Mais ganho exige alterar a definição do firmware ([manual da Field Box, secção 6](../field-box/BUILD.pt.md)) |
| 3 | Antena FPC de 2,4 GHz com cabo IPEX 1.0 | 1 | **Obrigatória**: a primeira configuração, as transferências de modos e as atualizações de firmware usam Wi-Fi |
| 4 | Botão arcade de 60 mm com LED de 5 V | 2 (ou 3) | Microinterruptor com COM, NO e NC; LED de 5 V (opcional) |
| 5 | Anel de LED WS2812B, 5 V | 1 | 24 LED é o valor por omissão do firmware; um anel de 12 ou 16 LED funciona com uma definição (`LED_COUNT`) |
| 6 | 74AHCT125 (ou 74HCT125), DIP-14, com suporte; condensador cerâmico de 100 nF; resistência de 330 ohm; condensador eletrolítico de 1000 µF 10 V+ | 1 de cada | O conversor de nível para os dados do anel, como na Field Box. **Não** o 74HC125 nem o 74AHC125 |
| 7 | Placa perfurada, cerca de 5 x 5 cm, e barras de pinos | 1 | A placa de interligação |
| 8 | Módulo medidor de bateria MAX17048 | 1 | Recomendado. Sem ele o firmware não sabe o nível da bateria e nunca envia `battery.low` |
| 9 | Célula de iões de lítio 18650 protegida, e um suporte de um só lugar com fios | 1 | **Protegida** (circuito de proteção incorporado), de uma marca de confiança. Ou um pack 1S pronto, com placa de proteção (BMS) e um cabo com chave |
| 10 | Conversor elevador (boost) de 5 V, entrada de 3,0-4,2 V | 1 | A peça da Field Box (saída de 5 V, 2,5 A ou mais) é uma escolha segura; quanto precisa um anel mais pequeno fica **por verificar na primeira montagem** |
| 11 | Porta-fusível em linha e fusível de 5 A; díodo Schottky 3 A+, 20 V+ (p. ex. 1N5822); interruptor principal, SPST, 5 A DC, tapado ou embutido | 1 de cada | Como na Field Box ([manual, secção 7](../field-box/BUILD.pt.md)) |
| 12 | Conectores de alavanca, de 3 e de 4 vias | 2 + 1 | Distribuição da bateria, da massa e dos 5 V |
| 13 | Extensão USB-C de painel com tampa, dados USB 2.0 | 1 | Opcional: carregar e gravar sem abrir a caixa |
| 14 | Caixa de derivação IP65, de cor viva, **não metálica**; bucins e um respiro de equalização de pressão | 1 | Grande o bastante para as peças acima com a tampa fechada ([secção 6](#6-caixa)) |
| 15 | Amplificador I2S MAX98357A e um altifalante de 4-8 ohm | 1 | Opcional: a única maneira de dar som a um Satélite |
| 16 | Etiquetas: "GAME PROP" e o nome da caixa | 2+ | Obrigatórias |

## 4. Ferramentas e segurança

As ferramentas são as da Field Box ([manual, secção 3](../field-box/BUILD.pt.md)):
um ferro de soldar com controlo de temperatura, um multímetro com apito de
continuidade, descarnadores de fio, alicate de crimpar ou solda, manga
termorretrátil, um berbequim com broca escalonada, e um saco à prova de fogo
para a célula enquanto trabalhas. Lê as
[regras de segurança](../field-box/BUILD.pt.md#4-regras-de-segurança) da Field Box (secção 4); aplicam-se
todas. As que mais importam aqui:

1. **Nunca alimentes a placa sem a antena LoRa ligada**, nem sequer por USB:
   transmitir para uma porta de antena aberta pode destruir o amplificador de
   entrada do rádio.
2. **Uma só célula de iões de lítio, em série (1S, 3,0-4,2 V).** A tomada de
   bateria da placa, o seu carregador e o MAX17048 são peças de uma só célula.
3. **Verifica a polaridade com o multímetro antes de cada ligação da bateria**:
   as fichas de bateria pequenas, de dois pinos, não têm polaridade normalizada.
4. **Célula protegida, fusível junto à célula, carregamento vigiado**, nunca
   numa caixa fechada, e só entre cerca de 0 e 45 °C. Nunca uses uma célula
   amolgada, inchada, quente ou abaixo de 2,5 V. Trabalha com a célula fora.
5. **Só sinais de 3,3 V** para a placa: o anel é comandado através do conversor
   de nível, e o medidor tem de puxar SDA e SCL para 3,3 V, nunca para 5 V.
6. **Nunca ligues o GPIO 5 ou 46** (o módulo frontal do rádio), **nem o GPIO 34
   ou 38-42** (o conector GNSS da placa).
7. **Nenhum jogo antes da verificação da potência de emissão** (BRING_UP.md,
   passo 10): o firmware limita a potência com um ganho de amplificador
   assumido que ainda não foi medido.
8. **Tem de parecer um dispositivo de jogo e aguentar pancadas.** Cor viva,
   "GAME PROP" na tampa e num lado, nada que pareça um explosivo. Os satélites
   ficam onde se luta, por isso BB e bolas de paintball vão acertar-lhes: monta
   a placa e a célula na placa traseira, longe das paredes, mantém a célula fora
   da linha de tiro, atrás da parede mais grossa da caixa, e nunca ponhas uma
   caixa onde se tenha de lhe atirar.

## 5. Pinos

Os pinos da Field Box, para as peças que um Satélite tem. São os valores por
omissão em
[`firmware/esp32/main/Kconfig.projbuild`](../../firmware/esp32/main/Kconfig.projbuild),
a referência se os dois alguma vez divergirem; `python3 tools/check_wiring.py`
falha se esta tabela divergir.

| Função | GPIO | Símbolo Kconfig | Cor do fio | Liga a | Nível | Notas |
| --- | --- | --- | --- | --- | --- | --- |
| Botão 1 (primeira equipa) | 4 | `ATALAIA_BTN1_PIN` | verde | microinterruptor NO; COM ao GND | 3,3 V | Ativo em baixo, pull-up interna |
| Botão 2 (segunda equipa) | 48 | `ATALAIA_BTN2_PIN` | verde | microinterruptor NO; COM ao GND | 3,3 V | |
| Botão 3 (opcional) | 44 | `ATALAIA_BTN3_PIN` | verde | microinterruptor NO; COM ao GND | 3,3 V | Linha de receção da UART0: sem entrada de consola na UART0 com ele (a consola USB-C não é afetada). Sem ligação, lê-se como nunca carregado |
| Dados do anel de luzes | 35 | `ATALAIA_LED_PIN` | branco | hub "LED data in", depois o 74AHCT125 e 330 ohm até ao DIN do anel | 3,3 V à entrada, 5 V à saída do conversor | É também o LED branco da placa, que pisca com ele |
| I2C SDA (medidor) | 17 | `ATALAIA_BATT_SDA_PIN` | azul | trilho SDA do hub, SDA do medidor | 3,3 V | O barramento I2C da própria placa, partilhado com o seu OLED |
| I2C SCL (medidor) | 18 | `ATALAIA_BATT_SCL_PIN` | amarelo | trilho SCL do hub, SCL do medidor | 3,3 V | |
| I2S BCLK (amplificador opcional) | 6 | `ATALAIA_AUDIO_BCLK_PIN` | cinzento | BCLK do amplificador | 3,3 V | |
| I2S LRCLK | 15 | `ATALAIA_AUDIO_LRCLK_PIN` | rosa | LRC do amplificador | 3,3 V | |
| I2S DOUT | 16 | `ATALAIA_AUDIO_DOUT_PIN` | castanho | DIN do amplificador | 3,3 V | |

Trilhos, não GPIO: VDD de lógica do medidor ao 3V3 do hub (violeta, 3,3 V); COM
dos botões, GND do medidor e GND do anel ao GND (preto); 5V do anel, VIN do
amplificador e LED dos botões ao trilho de 5 V (laranja, 5 V); o CELL+ do
medidor à derivação BAT+ (vermelho, 3,0-4,2 V). O endereço I2C do medidor é
0x36 e o do OLED da placa é 0x3C. A lista completa de pinos está na
[referência de pinos da Field Box](../field-box/BUILD.pt.md#15-referência-de-pinos) (secção 15).

Deixa todos os outros pinos da placa sem ligação. O firmware ainda comanda os
pinos do ecrã da Field Box (GPIO 1, 3, 33, 47) como saídas, por isso nada mais
pode ser ligado a eles; o GPIO 0, 45 e 46 são pinos de arranque (boot strap); os
pinos internos da placa estão listados no
[mapa de pinos da Field Box](../field-box/README.md#pin-assignments-default-kconfig----heltec-v43).

## 6. Caixa

<!-- PHOTO: satellite-enclosure.jpg | the drilled enclosure, lid and side views, with the layout marked -->
> **Fotografia a juntar depois da primeira montagem:** a caixa furada, vistas da
> tampa e do lado, com a disposição marcada.

Nenhuma caixa foi escolhida. Tem de:

- ser de **plástico** (ABS ou policarbonato), nunca de metal nem com tinta
  metalizada: o rádio tem de sair;
- ser IP65 ou melhor, com tampa com junta, de cor viva;
- levar a placa, a placa de interligação, o conversor elevador, o suporte da
  célula (preso, longe do conversor elevador e das antenas) e o medidor e o
  amplificador opcionais, com a tampa fechada e os cabos dobrados;
- levar os botões na tampa, afastados para que duas pessoas não choquem, o anel
  de luzes sob uma tampa translúcida ou uma janela difusora, o interruptor
  principal embutido ou tapado do lado oposto a quem joga, um respiro de
  equalização de pressão em baixo, e um ponto para cordão ou uma fixação para
  estaca ou cinta.

Prepara-a como a Field Box ([manual, secção 5](../field-box/BUILD.pt.md)): plano
em papel, mede cada furo a partir das tuas peças, fura antes de qualquer
eletrónica entrar, sela os furos que não usares, um saquinho de sílica gel
dentro. Os botões arcade não são à prova de água: mantém a eletrónica abaixo
deles, para que as gotas não caiam sobre uma placa.

**Verifica na primeira montagem:** a caixa mais pequena em que tudo cabe; o
sinal LoRa e de 2,4 GHz através da sua parede; que o OLED da placa se consegue
ler (através de uma tampa transparente ou de uma janela) onde está montado.

## 7. Revisão da placa e antenas

<!-- PHOTO: satellite-board-antennas.jpg | the board with both antenna leads fitted and labelled -->
> **Fotografia a juntar depois da primeira montagem:** a placa com os dois
> cabos de antena montados e etiquetados.

Exatamente como na Field Box ([manual, secção 6](../field-box/BUILD.pt.md)):

1. Lê o chip junto ao conector da antena LoRa: **KCT8103L** é uma V4.3 (a
   omissão do firmware), **GC1109** uma V4.2. Escreve a revisão na placa
   traseira; o firmware tem de ser compilado para ela.
2. Monta **as duas antenas antes de a placa ser alimentada**, e etiqueta cada
   cabo ("LoRa 868", "2.4 GHz"). Não adivinhes qual é qual: usa a serigrafia da
   placa e a sua documentação.
3. A antena LoRa dentro da caixa, na vertical e longe da célula e dos fios, ou
   fora, numa tomada SMA de painel; a antena FPC de 2,4 GHz deitada no interior
   da tampa ou de uma parede lateral.
4. Uma antena com mais de 2 dBi exige `CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI`
   definido para o seu ganho; nunca o baixes, nem a definição de ganho do
   módulo frontal.

## 8. Energia

<!-- PHOTO: satellite-power.jpg | the power path (holder, fuse, diode, switch, splices, boost converter) as built -->
> **Fotografia a juntar depois da primeira montagem:** o caminho da energia tal
> como ficou.

O caminho da energia da Field Box ([manual, secção 7](../field-box/BUILD.pt.md)
e [esquema 2/2](../field-box/wiring/field-box-power.svg)) com uma célula em vez
de duas em paralelo:

1. **Célula.** Carrega-a até ao máximo primeiro, num carregador de iões de lítio
   autónomo. Mete-a só com o interruptor desligado e o fusível fora. Mede os
   fios do suporte: 3,0-4,2 V, vermelho positivo.
2. **Fusível e díodo.** O porta-fusível no fio vermelho, junto ao suporte; o
   díodo Schottky da saída do porta-fusível (risca, cátodo) ao fio preto
   (ânodo), sob manga termorretrátil. Uma célula ligada ao contrário faz então
   queimar o fusível em vez da placa.
3. **Interruptor** da saída do fusível à derivação BAT+; o fio preto à derivação
   GND da bateria.
4. **Conversor elevador, sozinho primeiro.** A sua entrada a BAT+ e GND;
   fusível posto, interruptor ligado, **regula a saída para 5,0-5,2 V** antes de
   lhe ligares o que quer que seja. Desliga. A sua saída alimenta uma derivação
   de 5 V (anel de luzes, LED dos botões, amplificador, alimentação do
   conversor de nível).
5. **Cabo de bateria da placa por último** ([secção 9](#9-ligações-passo-a-passo),
   passo 7), depois de verificada a polaridade.

A placa faz a sua própria tensão de 3,3 V e carrega a célula por USB-C com o
interruptor principal **ligado** (interruptor desligado: a célula está
desligada e não carrega). As peças de 3,3 V (a lógica do medidor) tiram a
energia do pino 3V3 da placa, não do seu trilho Vext comutável.

**Verifica na primeira montagem:** a corrente em repouso e com o anel aceso, a
autonomia de um jogo com uma célula (o firmware acende o anel a 40 % por
omissão, `CONFIG_ATALAIA_LED_BRIGHTNESS_PCT`), e o tempo de carga.

## 9. Ligações, passo a passo

<!-- PHOTO: satellite-inside.jpg | the inside of the finished box, with the wiring routed -->
> **Fotografia a juntar depois da primeira montagem:** o interior da caixa
> acabada, com as ligações encaminhadas.

Célula fora, fusível fora, interruptor desligado, durante toda a secção. O
[esquema de sinais](../field-box/wiring/field-box-wiring.svg) da Field Box mostra
todos os fios abaixo; um Satélite deixa de fora o ecrã, o teclado e o seu
PCF8574, o leitor NFC e (a menos que queiras som) o amplificador. Etiqueta as
duas pontas de cada fio; só fio multifilar.

1. **Placa de interligação.** Como a da Field Box
   ([manual, secção 8](../field-box/BUILD.pt.md)), com menos pinos: trilhos
   3V3, GND e 5V (e SDA e SCL se montares o medidor), o 74AHCT125 no seu suporte
   com o pino 1 (1OE) ao GND, o pino 2 (1A) ao pino "LED data in", o pino 3
   (1Y) através da resistência de 330 ohm ao pino "LED data out", os pinos 4, 5,
   7, 9, 10, 12 e 13 ao GND, o pino 14 a 5V com o condensador de 100 nF do pino
   14 ao pino 7. Mantém os trilhos 5V e 3V3 em margens opostas. Verifica com o
   multímetro, com o chip fora: sem continuidade entre trilhos.
2. **Placa e trilhos.** Monta a placa em espaçadores, com as antenas montadas e
   o USB-C ao alcance. Liga o 3V3 e o GND da placa ao hub (e os GPIO 17 e 18 a
   SDA e SCL, para o medidor). Verifica: sem apito entre 3V3 e GND.
3. **Botões de equipa.** Cada microinterruptor: COM a um pino GND do hub, NO ao
   seu GPIO: botão 1 ao GPIO 4, botão 2 ao GPIO 48, um botão 3 opcional ao
   GPIO 44. O NC fica livre. LED dos botões (opcionais): LED+ ao trilho de 5 V,
   LED- ao COM. Verifica: cada fio de sinal só apita para o GND enquanto o
   botão está carregado.
4. **Anel de luzes.** O condensador de 1000 µF entre as pastilhas 5V e GND do
   anel (risca ao GND); **DIN** do anel (não o DOUT) ao "LED data out"; 5V e GND
   do anel às derivações de 5 V (0,5 mm²); GPIO 35 da placa ao "LED data in". Fio
   de dados com menos de cerca de 30 cm.
5. **Medidor (recomendado).** VCC (lógica) ao 3V3, GND, SDA, SCL do hub; antes de
   o ligares ao hub, verifica que o seu SDA e SCL medem 3,3 V ou menos quando
   está alimentado sozinho. A sua entrada de medição de bateria (CELL+) à
   derivação BAT+.
6. **Amplificador (opcional).** BCLK ao GPIO 6, LRC ao GPIO 15, DIN ao GPIO 16;
   VIN e GND às derivações de 5 V; o altifalante a SPK+ e SPK-, nenhum a tocar
   no GND.
7. **Cabo de bateria da placa.** O "5V in" do hub à derivação de 5 V. Faz o cabo
   para a tomada de bateria da placa a partir de BAT+ e da derivação GND da
   bateria, e depois **mede a sua polaridade** (célula posta, fusível posto,
   interruptor ligado, ficha fora da placa) contra as marcas + e - junto à
   tomada. Desliga, e só depois liga a ficha.

Inspeção final, antes de qualquer energia: as duas antenas montadas e
etiquetadas; sem continuidade entre BAT+ e GND, 5 V e GND, 3V3 e GND; a risca do
díodo virada para BAT+, a risca do condensador do anel virada para o GND; o
74AHCT125 do lado certo (entalhe junto ao pino 1); nada ligado aos pinos que a
[secção 5](#5-pinos) manda deixar livres.

## 10. Primeiro arranque e primeira gravação

1. **Caminho da energia.** Cabo de bateria da placa desligado, célula posta,
   fusível posto, interruptor ligado: derivação BAT+ a 3,0-4,2 V, derivação de
   5 V a 5,0-5,2 V, nada morno. Desliga, liga o cabo de bateria da placa.
2. **Só USB**, com o interruptor desligado: liga o computador à porta USB-C; a
   placa arranca; 3,3 V no trilho 3V3 do hub.
3. **Grava o firmware da Field Box**: transfere
   `atalaia-field-box-<version>-usb.zip` da
   [página de Releases do GitHub](https://github.com/vakaobr/atalaia-project/releases) (pré-alfa, não testado num
   campo; V4.3, EU868) e grava-o como diz a
   [secção 2.1 do guia de firmware](../../docs/manuals/pt/firmware.md), ou
   compila e grava-o tu, exatamente como diz a
   [secção 11 do manual da Field Box](../field-box/BUILD.pt.md):
   `python tools\docker_fw.py build`, e depois o esptool a partir do teu
   computador (o Docker no Windows não alcança as portas USB). Compila-o para a
   revisão da tua placa (V4.3 por omissão; a V4.2 precisa da alteração aí
   descrita). O [guia de firmware](../../docs/manuals/pt/firmware.md) tem os
   mesmos passos para Windows, macOS e Linux.
4. **Definições para um Satélite** (opcionais; em `firmware\esp32\build\sdkconfig`
   depois de uma compilação, e depois compilar de novo, como diz a
   [secção 12 do manual](../field-box/BUILD.pt.md)):

   | A tua montagem | Linha em `sdkconfig` |
   | --- | --- |
   | Anel de 12 ou 16 LED | `CONFIG_ATALAIA_LED_COUNT=12` (ou 16) |
   | Sem terceiro botão | `CONFIG_ATALAIA_BTN3_PIN=-1` |
   | Sem expansor do teclado (e portanto sem botão 4) | `CONFIG_ATALAIA_KP_P7_BUTTON=0` |
   | Sem amplificador | `CONFIG_ATALAIA_AUDIO_BCLK_PIN=-1` (áudio desligado) |
   | Antena com mais de 2 dBi | `CONFIG_ATALAIA_RADIO_ANTENNA_GAIN_DBI=` o seu ganho, arredondado para cima |

5. **Registo de arranque.** Num monitor série na porta USB: espera um aviso por
   cada peça que um Satélite não tem (`PCF8574 keypad not found`,
   `PN532 NFC reader not found`, e o do medidor se o deixaste de fora). É
   normal. Depois liga o interruptor e desliga o USB: arranca pela célula.
6. **Bring-up.** Faz os passos de
   [`BRING_UP.md`](../../firmware/esp32/docs/BRING_UP.md) (em inglês) que se
   aplicam: 1 (primeiro arranque), 2 (Vext: o OLED da placa), 4 (botões), 6
   (LED), 8 (áudio, se montado), 9 (bateria), **10 (rádio, potência de emissão:
   nenhum jogo antes dela)**, 10a (adoção), 10b e 10b2 (entrar no jogo de um
   controlador). Salta o passo do eFuse (passo 0) numa primeira caixa: queimar
   um eFuse não se desfaz.

## 11. Preparar para o campo

1. **Primeira configuração.** Uma caixa nova abre o seu portal de configuração
   Wi-Fi: liga-te a `atalaia-XXXX` com um telemóvel e define o nome da caixa, a
   região do rádio e um PIN de administração (não há PIN por omissão; PIN fáceis
   como 1234 são recusados). Escreve o nome na caixa.
2. **Adoção no teu campo**, por uma das duas maneiras que um Satélite tem
   (BRING_UP.md, passo 10a): o cabo USB ao controlador de campo (o separador
   **Adotar** da consola), ou o **código de emparelhamento** que uma caixa não
   adotada mostra no seu OLED, escrito em **Emparelhar por código (rádio)** na
   consola. Um cartão de campo precisa de um leitor NFC, que um Satélite não
   tem.
3. **Num jogo.** Na consola da organização, cria um jogo de um modo cujo papel
   precise só de botões de equipa (*Mestre e Satélites*, *Domínio*, *Domínio
   Total*, *Último Elemento*...), convida a caixa e
   dá-lhe o seu papel (`satellite` para um satélite). Manter premido um botão de
   equipa captura-a; o anel mostra a equipa que a ocupa.
4. **Mudá-la para outro campo** exige o seu PIN de administração, que a consola
   pede quando adota por cabo uma caixa de outro campo. Um Satélite não tem
   teclado, por isso não pode usar as entradas **Mudar de campo** e **Configurar
   o Wi-Fi** do teclado (o [guia de firmware](../../docs/manuals/pt/firmware.md),
   secção 5, descreve-as). Usa o cabo USB e a consola, e `@setup <PIN>` na
   consola USB para abrir de novo a página de configuração.
5. **Mais sobre a página de configuração, a adoção e as atualizações:** o
   [guia de firmware](../../docs/manuals/pt/firmware.md). O logótipo do campo
   precisa de um ecrã grande, por isso um Satélite nunca o mostra.

## 12. Resolução de problemas

O [manual da Field Box, secção 13](../field-box/BUILD.pt.md) cobre a placa, os
botões, o anel, o medidor, o amplificador e a energia. Para um Satélite em
particular:

| Sintoma | Causa provável e correção |
| --- | --- |
| O registo avisa que o teclado ou o leitor NFC não foi encontrado | Esperado: um Satélite não tem nenhum dos dois |
| Nunca mostra um menu de jogos | Esperado: sem teclado, só joga os jogos para que um controlador de campo o convida |
| O OLED fica escuro | O registo diz `SSD1306 OLED not found`: Vext (BRING_UP.md, passo 2) |
| Sem código de emparelhamento no OLED | A caixa já está adotada, ou entrou num jogo; uma caixa só mostra o código quando não está adotada |
| Anel de luzes apagado | Interruptor desligado (sem 5 V só com USB); DIN e DOUT trocados; o 74AHCT125 em falta ou ao contrário; o seu pino 1 fora do GND |
| Nível de bateria desconhecido, sem aviso de bateria fraca na consola | Sem MAX17048 montado, ou falta o fio de medição de bateria |
| Algo quente, um cheiro, fumo | Desliga logo, tira o fusível, tira a célula para um saco à prova de fogo |

Se encontrares uma avaria que não está aqui, ou um passo errado, abre uma
issue (fotografias são bem-vindas): este guia é corrigido a partir das
primeiras montagens.

---

Licença: este guia é CC-BY-SA-4.0; os projetos de hardware a que se refere são
CERN-OHL-S-2.0 ([LICENSING.md](../../LICENSING.md)).
