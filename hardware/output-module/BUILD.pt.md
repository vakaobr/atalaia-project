<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Guia de montagem do módulo de saídas I2C

Em inglês: [I2C output module build guide](BUILD.md).

O **módulo de saídas I2C** liga-se à [porta de expansão](../expansion-port/BUILD.pt.md)
de uma caixa e comuta até quatro cargas (uma sirene, um estroboscópio, uma
buzina, a entrada remota de baixa tensão de uma máquina de fumo) através de
relés ou MOSFETs, a partir de **uma alimentação própria**, atrás de um
**isolador I2C**, para que a caixa e as cargas nunca partilhem um fio. Uma
pequena placa RP2040 corre o seu firmware: a caixa só mantém uma saída ligada
enquanto continuar a escrever-lhe (a concessão), e o módulo guarda os seus
próprios limites rígidos. Escrito para alguém do clube que saiba soldar pinos
e fios e usar um multímetro, como o
[manual de montagem da Field Box](../field-box/BUILD.pt.md), que este guia
segue e para o qual remete em todos os passos que as montagens partilham.

> **Estado: desenhado, ainda não montado; posterior e opcional.** O módulo
> está decidido no rascunho do RFC «The expansion port»
> ([`docs/rfcs/0000-expansion-port.md`](../../docs/rfcs/0000-expansion-port.md),
> secção 3 (b), decisões EXP-16 e EXP-17, aprovadas por quem mantém o projeto
> em 2026-11-03), e fala o protocolo de expansão v1
> ([`protocol/expansion-port.md`](../../protocol/expansion-port.md)). **O seu
> firmware está escrito e testado só num computador**
> ([`firmware/output-module/`](../../firmware/output-module/README.md),
> incremento 11): compila para o RP2040 e o CI faz o seu ficheiro UF2 com o
> do módulo de alvo (`tools/docker_module.py`), mas **nunca correu numa
> placa**. **Ainda não se montou nenhum módulo a partir deste guia**, e o lado
> da caixa que o encontra e comanda as suas saídas nunca foi experimentado com
> um módulo real. Os passos marcados **Verificar na primeira montagem** são
> questões em aberto; reporta o que encontrares numa issue. A
> [secção 12](#12-o-que-espera-pela-bancada) lista o que espera. As fotografias
> serão acrescentadas depois da primeira montagem (fase HW2 do plano); este
> guia nunca usa fotografias de maquetas nem geradas.

**Usa primeiro a saída simples.** Para uma sirene, um estroboscópio ou um
comando de fumo, a **saída simples** (um GPIO, um interruptor de relé RC, uma
tomada M8:
[manual da Field Box, secção 9.10](../field-box/BUILD.pt.md#910-saída-simples-opcional))
é o caminho preferido (EXP-31): mais barata, mais simples, sem firmware
próprio. Este módulo é para uma caixa que precisa de **mais canais** do que
os GPIOs livres que tem, ou que quer saber se a alimentação das cargas está
lá (`SUPPLY_OK`).

> **NUNCA À REDE ELÉTRICA.** Este módulo comuta **apenas cargas SELV: no
> máximo 24 V DC, no máximo 2 A por canal** (EXP-17). Nada dentro dele, sobre
> ele ou ligado a ele toca alguma vez em ligações à rede elétrica (230 V ou
> 110 V), nem através de um relé marcado para isso. Um campo que queira
> comutar um aparelho de rede usa uma unidade de comutação de fabrico
> comercial, fechada, com marcação CE (ou certificação local) e uma entrada
> de controlo de baixa tensão, instalada como o fabricante indica, e comanda
> essa entrada a partir de um dos contactos secos deste módulo.
>
> **MÁQUINAS DE FUMO: SÓ ATRAVÉS DA SUA ENTRADA REMOTA DE BAIXA TENSÃO
> DOCUMENTADA** (uma entrada de contacto, um gatilho de 0-5 V ou de 12 V
> escrito no manual do fabricante), ou um aparelho de fumo a bateria feito
> para ser disparado por um contacto. **Muitas máquinas de fumo baratas de
> rede têm tensão de rede no cabo do comando com fios: nunca ligues um relé a
> uma, e nunca abras uma.** Se o manual não disser, por escrito, que a entrada
> remota é de baixa tensão, a máquina não se usa. O DMX está fora do âmbito.
>
> **Pirotecnia, ignitores e granadas de fumo estão fora do âmbito, sempre.**

## Índice

1. [O que estás a montar](#1-o-que-estás-a-montar)
2. [O que está decidido e o que não está](#2-o-que-está-decidido-e-o-que-não-está)
3. [Peças](#3-peças)
4. [Ferramentas e segurança](#4-ferramentas-e-segurança)
5. [Os dois lados: o isolador](#5-os-dois-lados-o-isolador)
6. [A alimentação própria do módulo](#6-a-alimentação-própria-do-módulo)
7. [Relés ou estado sólido](#7-relés-ou-estado-sólido)
8. [Cargas: contactos secos, fusíveis e díodos de roda livre](#8-cargas-contactos-secos-fusíveis-e-díodos-de-roda-livre)
9. [Os pinos](#9-os-pinos)
10. [Montagem, passo a passo](#10-montagem-passo-a-passo)
11. [Verificações, gravação e primeira ligação](#11-verificações-gravação-e-primeira-ligação)
12. [O que espera pela bancada](#12-o-que-espera-pela-bancada)
13. [Resolução de problemas](#13-resolução-de-problemas)

## 1. O que estás a montar

```
     LADO DA CAIXA (os 3,3 V da porta, poucos mA)  ║  LADO DO MÓDULO (alimentação própria, massa própria)
                                                   ║
porta ── cabo M12 ── ficha M12 ── P-MOSFET ── isolador ── placa RP2040 ── placa de relés ── contactos secos ── cargas
(EXP-1)   ≤ 2 m      macho       (cabo        lado 1 ║ lado 2   GP6-GP9   (ou placa de      (COM/NO do relé)   (cada uma com
                                  trocado)           ║          GP26      MOSFETs)                             a sua bateria
                                                     ║          sensor                                         e fusível)
                                                     ║  9-15 V ── fusível ── díodo ── buck 5 V ──┬── placa RP2040 (5 V / VSYS)
                                                     ║                                            └── bobinas dos relés
```

- **O lado da caixa** é a ficha M12 e o lado 1 do isolador, alimentado pelos
  3,3 V da porta (pino 1). É a única carga que o módulo põe na porta: poucos
  mA, bem abaixo dos 25 mA da porta (EXP-3, EXP-16).
- **O isolador** (classe ISO1540 / ADuM1250) passa o SDA e o SCL através de
  uma barreira: a massa da caixa e a massa do módulo **nunca se ligam**. O
  pico de um relé, um curto-circuito numa carga ou uma bateria errada ficam
  do lado do módulo.
- **O lado do módulo** tem a sua própria entrada de alimentação (9-15 V DC;
  uma bateria de 12 V é o típico, ou a bateria da própria sirene), o seu
  fusível e a sua proteção contra polaridade invertida, e um conversor buck
  para 5 V, que alimenta a placa RP2040 e as bobinas dos relés.
- **A placa RP2040** corre o firmware: o protocolo de expansão através do
  [núcleo de módulo](../../firmware/module-core/README.md), a concessão (todas
  as saídas desligadas 1,5 s depois de a caixa deixar de escrever), o tempo
  máximo ligado e o tempo mínimo desligado de cada canal, relés nunca mais
  depressa do que de 100 em 100 ms, todas as saídas desligadas ao arrancar,
  depois do watchdog e numa quebra de tensão, e um segundo tempo máximo
  ligado, independente (a guarda).
- **A placa de relés** dá **contactos secos**: fecha um circuito, não leva
  energia própria. Cada carga funciona com a sua bateria, através do seu
  fusível, através dos contactos.

Custo aproximado: 25-35 € sem a alimentação nem as cargas (placa RP2040 4 €,
isolador 4-6 €, placa de relés 3-5 €, conversor buck 2 €, fusível e proteção
2 €, caixa e bucins 8 €, ficha M12 4 €; secção 3 (b) do RFC, preços do
mercado amador, não um orçamento).

## 2. O que está decidido e o que não está

Decidido (com a origem de cada decisão):

| O quê | Decidido | Onde |
| --- | --- | --- |
| Para que serve | Mais canais de saída do que a saída simples, ou retorno (`SUPPLY_OK`); **posterior e opcional** | EXP-31 |
| Desenho | Um pequeno módulo próprio (placa RP2040, isolador I2C, alimentação própria) que comanda uma placa de relés comprada feita; **nunca uma placa de relés PCF8574 ou MCP23017 simples na porta** | EXP-15, EXP-16 |
| Porta e cabo | A tomada M12 fêmea, codificação A, de 5 pinos da caixa; uma ficha de painel **macho** no módulo; um cabo de sensor M12 macho-fêmea de no máximo 2 m | EXP-1, EXP-5; EXPI10-2 |
| Lado da caixa | Um isolador I2C, o seu lado 1 a única carga nos 3,3 V da porta (poucos mA); sem resistências de pull-up do lado da caixa (a placa da porta tem-nas) | EXP-3, EXP-16; P5J-17 |
| Lado do módulo | Entrada própria, 9-15 V DC, por um fusível e uma proteção contra polaridade invertida, para um conversor buck de 5 V para a placa RP2040 e as bobinas dos relés; nunca ligada aos pinos da porta | EXP-3, EXP-16 |
| Cargas | Contactos secos; **só SELV, no máximo 24 V DC e 2 A por canal**; **nunca à rede elétrica**; máquinas de fumo só pela entrada remota de baixa tensão documentada; nunca pirotecnia | EXP-17 |
| Placa de relés | Uma placa de relés opto-isolada de 1-4 canais com **disparo por nível alto** (entrada alta = relé ligado), bobinas de 5 V; ou uma placa de MOSFETs para cargas DC comutadas muitas vezes (estroboscópios) | EXP-16; este guia ([secção 7](#7-relés-ou-estado-sólido), EXPI11-5) |
| Endereço | 0x5C; dois jumpers de solda somam 1-3 (0x5D-0x5F) | EXP-7 |
| Modelo | `0x0002`, `out4`: 1 a 4 canais de saída comutada | `protocol/expansion-port.md`, secção 2 |
| Limites rígidos | O tempo máximo ligado e o tempo mínimo desligado de cada canal, definidos na compilação para o que está montado; relés nunca mais depressa do que de 100 em 100 ms; desligado ao arrancar, depois do watchdog, numa quebra de tensão; a caixa e o jogo só os podem baixar | EXP-13 |
| Os pinos | [Secção 9](#9-os-pinos), do `src/board.h` do firmware, os mesmos do módulo de alvo onde se aplicam | Firmware (EXPI11-6) |
| Peças exatas | Isolador ISO1540 ou ADuM1250, P-MOSFET classe AO3401 do lado da caixa, díodo de entrada classe 1N5819, conversor buck classe MP1584 ou LM2596 ([secção 3](#3-peças)) | Este guia (EXPI11-4 a EXPI11-8) |

Não decidido, ou ainda não feito:

- **Tudo o que é de bancada** ([secção 12](#12-o-que-espera-pela-bancada)): o
  isolador aos 3,0 V da porta, o nível baixo do barramento através do
  isolador e do buffer da porta, os relés a atracar com 3,3 V, a corrente na
  porta, a concessão com um cronómetro, o ruído junto a uma sirene a comutar.
- **Uma caixa real a comandar o módulo**: o lado da caixa (incremento 8) só
  foi testado num computador, contra um módulo simulado.
- **Uma placa de circuito impresso**: placa perfurada até lá.

## 3. Peças

Um conjunto por módulo. Cada peça tem o tipo e um exemplo que serve; uma
equivalente com as mesmas características também serve.

| # | Peça | Qtd | Para que serve | O que verificar |
| --- | --- | --- | --- | --- |
| 1 | Placa RP2040: **Raspberry Pi Pico** ou **RP2040-Zero** | 1 | Corre o firmware | Todos os pinos da [secção 9](#9-os-pinos) estão nos pinos de ambas as placas |
| 2 | Placa breakout com **isolador I2C**, classe **ISO1540** ou **ADuM1250** | 1 | **Mantém separadas a massa da caixa e a do módulo**: o SDA e o SCL atravessam uma barreira, mais nada | Dois pinos de alimentação separados (VCC1, VCC2) e duas massas (GND1, GND2). **As resistências de pull-up do lado 1 têm de sair** ([passo 4](#10-montagem-passo-a-passo)); o lado 2 precisa delas |
| 3 | P-MOSFET para tensão de porta baixa, classe **AO3401 / SI2301** (SOT-23, num adaptador), e uma resistência de 10 kohm | 1 + 1 | **Um cabo feito à mão com os fios trocados** não alimenta o isolador ao contrário, quase sem perda de tensão (como no módulo de alvo, EXPI10-8) | V(GS)th bem abaixo de 2 V |
| 4 | Ficha de painel M12 **macho**, codificação A, 5 pinos, IP67, com fios ou copos de solda | 1 | A ponta do cabo da porta no módulo | **Codificação A**, **5 pinos**; corpo de plástico, ou um corpo metálico que não toque em nada do lado do módulo ([secção 5](#5-os-dois-lados-o-isolador)) |
| 5 | **Placa de relés opto-isolada** de 4 canais, **disparo por nível alto** (ou com jumper de disparo alto/baixo posto em alto), **bobinas de 5 V** | 1 | Comuta as cargas: contactos secos (COM, NO, NC) | **Disparo por nível alto**; contactos para pelo menos 2 A a 30 V DC; um díodo em cada bobina na placa ([secção 7](#7-relés-ou-estado-sólido)) |
| 5b | ou uma **placa de MOSFETs** de 1-4 canais para cargas DC, do lado negativo, feita para **lógica de 3,3 V** | 1 | Estroboscópios e cargas comutadas mais depressa do que um relé deve | MOSFETs totalmente ligados com 3,3 V na porta (R(DS)on dado a V(GS) de 2,5 V ou menos); **a maioria destas placas não tem díodo de roda livre** ([secção 8](#8-cargas-contactos-secos-fusíveis-e-díodos-de-roda-livre)) |
| 6 | Resistências de 10 kohm, 1/4 W | 4 | **Pull-downs** nas entradas da placa de relés: todos os relés desligados enquanto o RP2040 está em reset, sem firmware ou a ser gravado | |
| 7 | Módulo conversor buck, entrada até pelo menos 24 V, saída **5 V**, pelo menos 1 A (classe **MP1584** ou **LM2596**) | 1 | 5 V para a placa RP2040 e para as bobinas dos relés, a partir da alimentação do módulo | **Acerta-o para 5,0 V antes de ligar seja o que for à saída** ([passo 2](#10-montagem-passo-a-passo)) |
| 8 | Porta-fusível em linha (lâmina ou 5 x 20 mm) e um fusível de **1 A lento** | 1 | **Um curto-circuito dentro do módulo** (um fio esmagado, um conversor avariado) funde o fusível, não a cablagem da bateria | O próprio módulo gasta bem menos de 0,5 A (quatro bobinas de 5 V e a placa): **Verificar na primeira montagem** |
| 9 | Díodo Schottky, classe **1N5819** (1 A, 40 V) | 1 | **Uma bateria ligada ao contrário** não chega ao conversor buck | Perde cerca de 0,4 V: não importa a 9-15 V |
| 10 | Terminal de parafuso de 2 polos ou ficha DC de painel | 1 | A entrada de alimentação do módulo: «SUPPLY 9-15 V» | Nunca o mesmo tipo de ligador das saídas das cargas nem o M12 |
| 11 | Porta-fusível em linha e fusível **dimensionado para cada carga, no máximo 2 A** | 1 por carga | **Um curto-circuito numa carga ou no seu cabo** funde o seu próprio fusível, junto à sua bateria | Junto ao terminal positivo da bateria da carga |
| 12 | Díodo retificador, classe **1N4007** (ou 1N5819 para um canal de MOSFET rápido) | 1 por carga indutiva | **Roda livre**: em paralelo com uma sirene de motor, uma buzina, um solenoide ou a bobina de um relé externo, para que o seu pico não faça arco nos contactos nem mate um MOSFET ([secção 8](#8-cargas-contactos-secos-fusíveis-e-díodos-de-roda-livre)) | A risca para o lado positivo da carga |
| 13 | Sensor de alimentação (opcional): resistências de 100 kohm e 22 kohm a 1 %, um condensador de 100 nF, um díodo Schottky classe BAT85, um terminal de 2 polos «SENSE» | 1 conjunto | `SUPPLY_OK`: a caixa vê se a bateria das cargas está lá e acima de 9 V ([secção 6](#6-a-alimentação-própria-do-módulo)) | Só com um canal marcado `sense` na lista de canais do firmware |
| 14 | LED de estado (qualquer cor) e uma resistência de 1 kohm | 1 + 1 | Pisca enquanto a caixa pede `LOCATE`, depressa numa falha | |
| 15 | Pinos de 2 vias e jumpers, ou duas ilhas de solda | 2 | Os jumpers de endereço (GP2, GP3 à massa) | |
| 16 | Caixa IP65 de plástico, cerca de 150 x 110 x 70 mm, com bucins (PG7 / PG9) | 1 | Mantém fora a água e a sujidade; os cabos das cargas entram pelos seus próprios bucins | Espaço para a placa de relés, o conversor buck, a placa RP2040 e o isolador, com o lado da caixa afastado ([secção 5](#5-os-dois-lados-o-isolador)) |
| 17 | Terminais de parafuso para as cargas (2 ou 3 polos por canal), placa perfurada de cerca de 7 x 9 cm, fio multifilar de 0,25 mm² e 0,75 mm², manga termorretrátil, abraçadeiras | 1 conjunto | A placa do módulo e a sua cablagem; 0,75 mm² para a alimentação e a corrente das cargas | |
| 18 | Etiquetas: «EXPANSION 3.3 V», «SUPPLY 9-15 V DC», «OUT 1» a «OUT 4», «SÓ SELV, NUNCA À REDE» | 1 conjunto | Diz o que é cada ligador | |

**Nunca uma «placa de relés I2C» PCF8574 ou MCP23017 simples na porta**,
mesmo que não precise de firmware: não tem concessão (um relé fica ligado se
a caixa encravar), responde onde a caixa procura o expansor do teclado (uma
caixa sem teclado faria os relés estalar a cada 10 ms), os relés podem
ligar-se todos ao arrancar, e as bobinas funcionariam com os 3,3 V da porta
(EXP-15).

## 4. Ferramentas e segurança

As ferramentas são as da Field Box ([manual, secção 3](../field-box/BUILD.pt.md#3-ferramentas-e-consumíveis)),
mais um ferro de ponta fina para o MOSFET SOT-23 (ou compra-o já num
adaptador) e uma chave de fendas pequena para o potenciómetro do conversor
buck. Lê as [regras de segurança](../field-box/BUILD.pt.md#4-regras-de-segurança)
do manual; aplicam-se todas. Para o módulo de saídas em particular:

1. **Nunca à rede elétrica** ([o aviso acima](#guia-de-montagem-do-módulo-de-saídas-i2c)).
   Só cargas SELV, no máximo 24 V DC e 2 A por canal. Uma placa de relés com
   «10 A 250 V AC» impresso continua a ser usada só em SELV aqui.
2. **Máquinas de fumo só pela sua entrada remota de baixa tensão
   documentada**; nunca abras uma máquina de fumo, nunca ligues nada ao cabo
   de um comando cuja tensão o manual não diga por escrito.
3. **Alimentação desligada, baterias das cargas desligadas, cabo M12
   desligado** enquanto soldas ou ligas o que quer que seja.
4. **Todas as baterias atrás de um fusível.** A alimentação do módulo pelo
   seu fusível (peça 8), cada carga pelo seu (peça 11), cada fusível junto ao
   terminal positivo da sua bateria. Uma bateria de chumbo-ácido ou LiFePO4 de
   12 V consegue dar centenas de amperes num curto-circuito: o bastante para
   derreter um fio e começar um incêndio.
5. **Nada do lado do módulo chega alguma vez à porta.** A porta é o
   barramento de 3,3 V da caixa; só o lado 1 do isolador está ligado a ela
   (EXP-3, P5J-15). A alimentação, a massa e as cargas do módulo nunca tocam
   nos pinos 1-5 do M12.
6. **O pino 5 fica sem ligação** (EXP-1).
7. **Grava o firmware com a alimentação desligada e o cabo M12 desligado**
   ([secção 11.3](#113-gravação)): uma RP2040-Zero liga os 5 V do USB
   diretamente ao seu pino de 5 V.
8. **Proteção auditiva** junto a sirenes e buzinas, também na bancada;
   **fumo** nunca numa sala fechada sem a aprovação do espaço; um
   estroboscópio pode desencadear epilepsia fotossensível: avisa quem joga
   antes do jogo.
9. **Um adereço de jogo**: cores vivas, etiquetas «GAME PROP», nada que
   pareça um explosivo (secção 17 da especificação), e saídas usadas dentro da
   lei local.

## 5. Os dois lados: o isolador

O isolador é a fronteira do módulo. Tudo no seu **lado 1** pertence à caixa;
tudo no seu **lado 2** pertence ao módulo. Só o SDA e o SCL a atravessam,
como sinais.

| | Lado 1: o lado da caixa | Lado 2: o lado do módulo |
| --- | --- | --- |
| Alimentação | Pino 1 do M12 (os 3,3 V da porta, cerca de 3,0 V depois do díodo da caixa), pelo P-MOSFET, ao VCC1 | O pino 3V3 da placa RP2040 (o seu próprio regulador, a partir dos 5 V do módulo) ao VCC2 |
| Massa | Pino 3 do M12 ao GND1, **e a mais nada** | GND2, o GND da placa RP2040, o negativo da saída e da entrada do conversor buck, o GND da placa de relés, o negativo da entrada de alimentação |
| SDA, SCL | Pinos 2 e 4 do M12 ao SDA1, SCL1 | SDA2, SCL2 ao GP4, GP5 |
| Pull-ups | **Nenhuma** no módulo: a placa da porta da caixa tem-nas (P5J-17). Tira as resistências do lado 1 de uma placa breakout | Cerca de **4,7 kohm** cada, do SDA2 e do SCL2 ao VCC2 (muitas vezes já na placa breakout; monta-as se não estiverem) |
| Corrente | Poucos mA da porta: **a medir**, no máximo 5 mA (secção 3 (b) do RFC) | Da alimentação do módulo |

Regras que mantêm os dois lados separados:

- **Nenhum fio, pista, parafuso ou peça metálica junta os dois lados.** Na
  placa perfurada, deixa um intervalo de pelo menos 5 mm (corta as pistas)
  entre a cablagem do lado 1 e tudo o resto, também por baixo do próprio
  isolador.
- **O corpo metálico da ficha M12**, se tiver, não toca em nada do lado do
  módulo: monta-a na parede da caixa de plástico, longe dos parafusos da
  placa de relés. A malha de um cabo blindado não se liga no módulo.
- O isolamento aqui é **funcional, não uma barreira de segurança**: mantém
  separadas as massas e as correntes das cargas. Nunca é razão para chegar
  perto da rede elétrica.

**Verificar na primeira montagem:**

- **O isolador a cerca de 3,0 V.** O lado 1 do ISO1540 e do ADuM1250 aceita
  3,0 V a 5,5 V; a porta dá cerca de 3,0 V (menos uns mV no P-MOSFET), o
  fundo dessa gama. Mede o VCC1 com o módulo ligado e a funcionar. Um isolador
  cujo lado 1 comece nos 2,25 V (classe ISO1640) é a alternativa se não
  funcionar com fiabilidade.
- **O nível baixo do barramento através do isolador e do buffer da porta.**
  Estes isoladores puxam o seu lado 1 para um nível baixo um pouco elevado
  (umas centenas de mV, de propósito, para distinguir os seus níveis baixos
  dos da caixa). Confirma num osciloscópio, na ponta da caixa, que um nível
  baixo continua bem abaixo do limiar de entrada do TCA4307 e que a caixa lê
  o `IDENT` do módulo todas as vezes (teste de bancada,
  [secção 12](#12-o-que-espera-pela-bancada)).

## 6. A alimentação própria do módulo

**Nunca da caixa** (EXP-3). O módulo traz a sua:

```
SUPPLY + ── fusível 1 A ── 1N5819 (risca para o buck) ── buck IN+ ── buck OUT+ 5,0 V ──┬── pino 5 V da placa RP2040 (RP2040-Zero) / VSYS (Pico)
SUPPLY − ─────────────────────────────────────────────── buck IN− ── buck OUT−  GND ───┴── VCC, JD-VCC e GND da placa de relés
```

- **Entrada de 9-15 V DC**: uma bateria de chumbo-ácido ou LiFePO4 de 12 V,
  ou a bateria da própria sirene. A mesma bateria pode também alimentar as
  cargas, cada uma pelo seu fusível
  ([secção 8](#8-cargas-contactos-secos-fusíveis-e-díodos-de-roda-livre)).
- **Primeiro o fusível**, junto ao terminal positivo da bateria, depois o
  **díodo contra a polaridade invertida**: uma bateria ao contrário fica
  parada antes do conversor buck.
- **O conversor buck acertado para 5,0 V** antes de ligar seja o que for à
  sua saída: o potenciómetro vem muitas vezes acertado para 12 V ou mais, o
  que destruiria a placa RP2040 e a placa de relés.
- **5 V para a placa RP2040**: numa Pico, o pino VSYS (pino 39); numa
  RP2040-Zero, o pino 5 V. A placa faz os seus próprios 3,3 V, que alimentam
  o lado 2 do isolador, as pull-ups e o limitador do sensor de alimentação.
- **5 V para o VCC da placa de relés**, com o jumper JD-VCC posto (bobinas e
  optoacopladores com os mesmos 5 V; o que mantém a caixa à parte é o
  isolador I2C).

O reset de ligação e de quebra de tensão do próprio RP2040 reinicia o módulo
quando a alimentação desce demasiado; volta com todas as saídas desligadas
(EXP-13).

**O sensor de alimentação (opcional, `SUPPLY_OK`).** Um divisor de uma
entrada «SENSE» para o GP26 (ADC0) deixa a caixa ver se a bateria das cargas
está lá:

```
SENSE + ── 100 kohm ──┬── GP26 (ADC0)
                      ├── 22 kohm ── GND
                      ├── 100 nF ─── GND
                      └── BAT85 (risca para o 3V3) ── 3V3 do RP2040
SENSE − ── GND (o do lado do módulo)
```

Liga o «SENSE +» ao terminal positivo da bateria de que as cargas dos canais
sensorizados se alimentam (depois do seu fusível), e o «SENSE −» ao seu
negativo; o negativo dessa bateria passa então a partilhar a massa do lado do
módulo, nunca a da caixa. 15 V dão 2,7 V no GP26; o BAT85 limita tudo o que
passe de 3,3 V. O firmware indica `SUPPLY_OK` a partir de **9,0 V** e tira-o
abaixo de **8,5 V**, filtrado para que o pico de um relé não o troque, e
**só para canais marcados `sense`** na sua lista de canais
([README do firmware](../../firmware/output-module/README.md#the-channel-list)):
sem o divisor montado, não marques nenhum. A tolerância do divisor e a
referência do ADC do RP2040 (os seus 3,3 V) determinam o rigor desses
limiares: **Verificar na primeira montagem** contra um multímetro.

## 7. Relés ou estado sólido

Cada canal é um **relé** ou de **estado sólido**, e o firmware sabe qual (a
sua lista de canais, definida na compilação: `relay` ou `solid`):

| | Relé (contactos) | Estado sólido (um MOSFET) |
| --- | --- | --- |
| Placa | Uma placa de relés opto-isolada de 4 canais, **disparo por nível alto**, bobinas de 5 V | Uma placa de MOSFETs do lado negativo para **lógica de 3,3 V** |
| Comuta | DC **e** qualquer carga de baixa tensão, isolada do módulo: contactos secos | Só DC, o seu lado negativo, partilhando a massa do lado do módulo |
| Rapidez | Nunca mais depressa do que de **100 em 100 ms**; padrões a partir de 100 ms ligado e desligado (o firmware recusa mais rápido) | Padrões a partir de **10 ms** |
| Bom para | Sirenes, buzinas, a entrada remota de uma máquina de fumo, tudo o que queira um contacto simples | Estroboscópios e LEDs a piscar depressa, muitas vezes por jogo |
| Cuidado com | A corrente das bobinas nos 5 V (cerca de 70-90 mA cada: **Verificar na primeira montagem**) | Uma carga que precise de um contacto e não de um negativo comutado (um comando de fumo: usa um relé) |

**O disparo por nível alto, e as pull-downs, são o que torna verdade o
«desligado ao arrancar».** Muitas placas de relés baratas são de **disparo
por nível baixo** (uma entrada baixa liga o relé). Um pino do RP2040 está em
baixo ou solto enquanto o RP2040 reinicia, arranca ou é gravado, e o seu
nível alto de 3,3 V não consegue manter desligada com fiabilidade uma entrada
de disparo baixo a 5 V: **uma placa dessas podia ligar uma sirene ou uma
máquina de fumo sozinha. Não uses uma** (ou põe o seu jumper de disparo em
alto). Com uma placa de disparo por nível alto, uma pull-down de 10 kohm em
cada entrada (peça 6) mantém todos os relés desligados desde o momento em que
a alimentação chega até o firmware comandar os pinos, e o firmware põe-nos em
baixo antes de tudo o resto.

**Verificar na primeira montagem:** cada relé atraca com fiabilidade com os
3,3 V do RP2040 na sua entrada (uma placa de optoacopladores de disparo por
nível alto gasta aí uns mA), e solta logo a 0 V.

A lista de canais do firmware diz à caixa o que está montado e os limites do
próprio módulo; por exemplo, uma sirene, um estroboscópio num MOSFET e um
comando de fumo com 30 s ligado e 30 s desligado:

```
relay:siren:60:0,solid:strobe:120:0,relay:smoke:30:30
```

Define o tempo máximo ligado e o tempo mínimo desligado de cada canal a
partir do manual do próprio aparelho (o ciclo de trabalho de uma máquina de
fumo, o de uma sirene). Quem administra a caixa pode baixá-los, nunca
subi-los (EXP-13). O UF2 do CI e das versões publicadas traz a lista por
omissão (quatro relés, genéricos, no máximo 30 s ligados cada); outras cargas
pedem uma compilação própria
([README do firmware](../../firmware/output-module/README.md#building)).

## 8. Cargas: contactos secos, fusíveis e díodos de roda livre

**Um canal de relé** (COM e NO; o NC fica por usar, para que um módulo
morto seja um circuito aberto):

```
bateria da carga + ── fusível (≤ 2 A, para a carga) ── COM ┤relé├ NO ── carga + ── carga ── carga − ── bateria da carga −
                                                                     └─ 1N4007, risca para carga + ─┘   (cargas indutivas)
```

**Um canal de estado sólido** (um MOSFET do lado negativo: é o negativo da
carga que se comuta, e o negativo da bateria da carga junta-se à massa do
lado do módulo):

```
bateria da carga + ── fusível (≤ 2 A) ── carga + ── carga ── carga − ── OUT− da placa de MOSFETs ── (MOSFET) ── GND ── bateria da carga −
                                          └─ 1N5819 (ou 1N4007), risca para carga + ─┘
```

- **Um fusível por carga, no máximo 2 A, dimensionado para a carga**, junto
  ao terminal positivo da sua bateria (EXP-17). A característica do próprio
  relé não o substitui.
- **Díodos de roda livre**: uma sirene de motor, uma buzina, um solenoide,
  uma pequena bomba ou a bobina de um relé externo são **indutivos**: quando
  desligam, a corrente salta para uma tensão alta que faz arco nos contactos
  de um relé e mata um MOSFET. Monta um díodo mesmo em paralelo com a carga,
  a risca para o lado positivo. Um estroboscópio ou uma luz LED sem motor não
  precisa; na dúvida, monta-o. A maioria das placas de MOSFETs não tem
  nenhum: num canal de estado sólido o díodo é **obrigatório** para qualquer
  carga indutiva. Os díodos das bobinas da placa de relés (confirma que estão
  lá) protegem a placa, não as cargas.
- **A entrada remota de uma máquina de fumo**: um canal de relé, o COM e o NO
  ligados diretamente aos dois contactos que o manual indica, nada mais no
  circuito (sem bateria, sem díodo), e só se o manual disser por escrito que
  a entrada é de baixa tensão.
- **Fio de 0,75 mm²** para as cargas (2 A), nos seus próprios bucins e
  terminais, nunca pelo M12 nem pelo ligador da alimentação do módulo.

## 9. Os pinos

Os pinos são os do firmware
([`firmware/output-module/src/board.h`](../../firmware/output-module/src/board.h));
o `python3 tools/check_wiring.py` falha se esta tabela não estiver de acordo
com eles. Todos os pinos estão nos pinos de uma Raspberry Pi Pico e de uma
RP2040-Zero.

<!-- check_wiring: output-module-pins -->
| Pino do RP2040 | Nome no firmware | O quê | Ligado a |
| --- | --- | --- | --- |
| GP2 | `OUT_PIN_JUMPER_A0` | Jumper de endereço A0: fechado à massa soma 1 | Um jumper à massa do lado do módulo |
| GP3 | `OUT_PIN_JUMPER_A1` | Jumper de endereço A1: fechado à massa soma 2 | Um jumper à massa do lado do módulo |
| GP4 | `OUT_PIN_SDA` | I2C0 SDA, o alvo I2C | O SDA2 do isolador (4,7 kohm ao VCC2) |
| GP5 | `OUT_PIN_SCL` | I2C0 SCL | O SCL2 do isolador (4,7 kohm ao VCC2) |
| GP6 | `OUT_PIN_CH0` | Canal 0 («OUT 1»), alto: ligado | O IN1 da placa de relés ou de MOSFETs; 10 kohm à massa |
| GP7 | `OUT_PIN_CH1` | Canal 1 («OUT 2») | IN2; 10 kohm à massa |
| GP8 | `OUT_PIN_CH2` | Canal 2 («OUT 3») | IN3; 10 kohm à massa |
| GP9 | `OUT_PIN_CH3` | Canal 3 («OUT 4») | IN4; 10 kohm à massa |
| GP14 | `OUT_PIN_LED` | O LED de estado | Ânodo do LED; o cátodo por 1 kohm à massa |
| GP26 | `OUT_PIN_SUPPLY_SENSE` | ADC0: o sensor de alimentação (opcional) | O meio do divisor ([secção 6](#6-a-alimentação-própria-do-módulo)) |

O endereço com os jumpers: nenhum 0x5C, A0 0x5D, A1 0x5E, ambos 0x5F. O
firmware lê-os uma vez ao arrancar. O LED da própria Pico (GP25) pisca com o
GP14; o LED RGB de uma RP2040-Zero fica apagado. As outras ligações do
módulo: 5 V no VSYS da Pico (pino 39) ou no pino 5 V da RP2040-Zero, o seu
pino 3V3 ao VCC2 do isolador, o seu GND à massa do lado do módulo.

**A ficha M12** (a ficha de painel macho do módulo, só lado 1):

| Pino M12 | Cor do fio | Sinal | Ligado a |
| --- | --- | --- | --- |
| 1 | castanho | 3,3 V da caixa | O dreno do P-MOSFET; a fonte ao VCC1 do isolador; a porta por 10 kohm ao GND1 |
| 2 | branco | SDA | O SDA1 do isolador |
| 3 | azul | GND da caixa | O GND1 do isolador, **e mais nada** |
| 4 | preto | SCL | O SCL1 do isolador |
| 5 | cinzento | sem ligação | Nada: corta o fio curto e isola-o |

## 10. Montagem, passo a passo

<!-- PHOTO: output-module-inside.jpg | the finished module open: the M12 connector and isolator kept apart from the RP2040 board, the buck converter and the relay board -->
> **Fotografia a acrescentar depois da primeira montagem:** o módulo
> acabado, aberto.

1. **Planeia a caixa.** A ficha M12 e o isolador num canto (o lado da
   caixa), a entrada de alimentação e o seu fusível noutro, os terminais da
   placa de relés virados para os bucins das cargas. Fura os buracos, monta a
   ficha M12 com o O-ring do lado de fora, os bucins e o ligador da
   alimentação. Etiqueta cada um (peça 18).
2. **Acerta o conversor buck**, sozinho: liga só a sua entrada à alimentação
   (pelo fusível), roda o potenciómetro até um multímetro na saída marcar
   **5,0 V**, desliga. Marca o potenciómetro com uma gota de tinta.
3. **O caminho da alimentação** na placa perfurada (0,75 mm²): o + do
   ligador de entrada ao porta-fusível, o fusível ao ânodo do 1N5819, o seu
   cátodo (a risca) ao IN+ do buck; o − da entrada ao IN− do buck. Um trilho
   duplo a partir do OUT+ (5 V) e do OUT− (GND) do buck.
4. **O isolador.** Sem alimentação, mede o SDA1 e o SCL1 ao VCC1: as
   **pull-ups do lado 1** de uma placa breakout **têm de sair** (corta o seu
   jumper ou tira as duas resistências), porque a placa da porta da caixa
   puxa o barramento. Mede o SDA2 e o SCL2 ao VCC2: cerca de **4,7 kohm**
   cada; monta duas resistências se não houver. Monta-o por cima do
   intervalo entre os dois lados da placa perfurada.
5. **O lado da caixa.** Os fios da ficha M12, com menos de 10 cm, nas cores
   do cabo: pino 1 castanho ao dreno do P-MOSFET, a sua fonte ao VCC1, a sua
   porta por 10 kohm ao GND1; pino 2 branco ao SDA1; pino 3 azul ao GND1;
   pino 4 preto ao SCL1; **pino 5 cinzento cortado curto e isolado**. Mais
   nada deste lado.
6. **A placa RP2040.** 5 V do trilho ao VSYS (Pico) ou ao 5 V
   (RP2040-Zero), GND ao GND do trilho. O seu 3V3 ao VCC2 do isolador, o seu
   GND ao GND2. GP4 ao SDA2, GP5 ao SCL2. Os jumpers de endereço do GP2 e do
   GP3 à massa; o LED e a sua resistência de 1 kohm no GP14. **Deixa a
   tomada USB da placa acessível** para gravar o firmware.
7. **A placa de relés (ou de MOSFETs).** O seu VCC (e o JD-VCC, com o jumper
   posto) ao trilho de 5 V, o seu GND ao GND do trilho. GP6-GP9 ao IN1-IN4,
   cada um com a sua **pull-down de 10 kohm à massa** na entrada da placa.
   Com menos canais montados, deixa os pinos GP por usar sem ligação (o
   firmware mantém-nos em baixo).
8. **O sensor de alimentação** (opcional): o divisor, o seu condensador e o
   seu BAT85 junto ao GP26, e o terminal de 2 polos «SENSE»
   ([secção 6](#6-a-alimentação-própria-do-módulo)).
9. **Os terminais das cargas.** Do COM e do NO de cada relé (ou dos
   terminais OUT de cada MOSFET) aos terminais «OUT 1»-«OUT 4» junto aos
   bucins, em 0,75 mm². As cargas, os seus fusíveis e os seus díodos ligam-se
   fora do módulo
   ([secção 8](#8-cargas-contactos-secos-fusíveis-e-díodos-de-roda-livre)).
10. **Arruma.** Prende todos os fios para que nada puxe uma soldadura e nada
    do lado do módulo possa balançar até ao lado da caixa. Só fecha a caixa
    depois da [secção 11](#11-verificações-gravação-e-primeira-ligação).

## 11. Verificações, gravação e primeira ligação

### 11.1 Antes de qualquer energia (multímetro; alimentação, cargas e cabo M12 todos desligados)

- [ ] **Isolamento**: pino 3 do M12 (a massa da caixa) à massa do lado do
      módulo, ao − da entrada de alimentação, a cada terminal dos relés e ao
      GND da placa RP2040: **aberto** (sem continuidade, mais do que uns
      Mohm). É o teste de bancada 7 do RFC.
- [ ] Pinos 1, 2 e 4 do M12 a qualquer coisa do lado do módulo: **aberto**.
- [ ] Pino 5 do M12 a todos os outros pinos: **aberto**.
- [ ] O + da entrada de alimentação ao −: sem curto-circuito (uns kohm ou
      mais é o conversor buck).
- [ ] Teste de díodo no 1N5819: cerca de 0,2-0,4 V no sentido do buck,
      aberto ao contrário.
- [ ] Cada entrada dos relés (IN1-IN4) à massa: cerca de **10 kohm** (a
      pull-down).
- [ ] O COM ao NO de cada relé: **aberto**; o COM ao NC: fechado (o relé em
      repouso).
- [ ] SDA2 e SCL2 ao VCC2: cerca de 4,7 kohm; SDA1 e SCL1 ao VCC1:
      **aberto** (sem pull-ups do lado 1).

### 11.2 Primeira energia, sem firmware, sem caixa

1. Cargas desligadas, cabo M12 desligado. Liga a alimentação.
2. A saída do buck: **5,0 V**. O 3V3 da placa RP2040: cerca de 3,3 V. O
   VCC2 do isolador: o mesmo.
3. **Nenhum relé estala**, e cada entrada dos relés lê 0 V. Repete 10 vezes
   (desliga e liga a alimentação): um relé que estala ao arrancar quer dizer
   uma placa de disparo baixo ou uma pull-down em falta: para e corrige
   ([secção 7](#7-relés-ou-estado-sólido)).
4. Desliga a alimentação.

### 11.3 Gravação

O CI faz o ficheiro UF2 com a lista de canais por omissão, com o do módulo
de alvo (`python3 tools/docker_module.py build`); uma versão publicada traz
`atalaia-output-module-<versão>.uf2`. Para outras cargas, compila-o com a
lista de canais do que está montado
([README do firmware](../../firmware/output-module/README.md#building)).

1. **Alimentação desligada, cabo M12 desligado, cargas desligadas.**
2. Mantém carregado o botão BOOTSEL da placa, liga-a à USB de um
   computador, solta-o; copia o ficheiro `.uf2` para a unidade que aparece. A
   placa reinicia sozinha.
3. Desliga a USB.

### 11.4 Primeira ligação com o firmware

1. Cargas desligadas, cabo M12 desligado. Liga a alimentação.
2. **Nenhum relé estala**, ao arrancar nem depois (20 ciclos de energia,
   observados). O LED fica apagado. Um **LED a piscar depressa** quer dizer
   que o firmware recusou a sua lista de canais: volta a compilá-lo com uma
   lista válida.
3. Desliga a alimentação. Liga as cargas (cada uma pelo seu fusível) mas
   deixa o M12 desligado: nada comuta, porque nenhuma caixa está a escrever
   ao módulo.

### 11.5 Numa caixa

1. Com a caixa desligada, liga o módulo à sua porta de expansão, e liga a
   alimentação do módulo.
2. Liga a caixa. Ela envia `ALL_OFF` e lê o módulo: a lista de módulos da
   caixa mostra `5c:out4/1.0.0:` e os nomes dos canais (`node.modules`).
3. As saídas do módulo estão **desligadas na caixa até quem a administra as
   ativar** (EXP-28), na caixa, com a função e o tempo máximo ligado de cada
   canal. O teste de 1 s da administração faz então estalar cada relé à vez.
4. Os testes de bancada da [secção 12](#12-o-que-espera-pela-bancada).

## 12. O que espera pela bancada

| O quê | Precisa de | Quando |
| --- | --- | --- |
| Teste de bancada 5 do RFC: com um relé ligado, cortar a energia da caixa, reiniciar a caixa, cortar o cabo, desligar o módulo: **desligado em 1,5 s** de cada vez (um cronómetro num vídeo) | Uma caixa | Bancada (HW2) |
| Teste de bancada 6 do RFC: ruído: uma sirene de 12 V e um estroboscópio a comutar durante 30 minutos junto à caixa e ao seu cabo; contar erros de CRC e leituras falhadas | Uma caixa | Bancada (HW2) |
| Teste de bancada 7 do RFC: isolamento (sem continuidade do pino 3 do M12 ao lado do módulo) | Um multímetro | Agora ([11.1](#111-antes-de-qualquer-energia-multímetro-alimentação-cargas-e-cabo-m12-todos-desligados)) |
| Teste de bancada 10 do RFC: fumo: um aparelho de fumo a bateria ou uma máquina com entrada de baixa tensão documentada, disparado pela explosão do Bomb, parado pelo «Todas as saídas desligadas» do GM e pelo fim do jogo | Uma caixa, o manual do aparelho | Bancada (HW2) |
| O lado 1 do isolador aos 3,0 V da porta, e o nível baixo do barramento através do isolador e do buffer da porta ([secção 5](#5-os-dois-lados-o-isolador)) | Uma caixa, um osciloscópio | Bancada (HW2) |
| A corrente do módulo no pino 1 da porta (esperada: poucos mA, no máximo 5 mA) | Um multímetro em série com o pino 1 | Bancada (HW2) |
| Os relés a atracar com 3,3 V; a corrente das bobinas; a corrente da própria alimentação do módulo; o valor do fusível de entrada | Um multímetro | Agora |
| Os limiares do sensor de alimentação contra um multímetro | Uma fonte variável | Agora; a caixa mostra o `SUPPLY_OK` |
| O watchdog e a guarda na placa (um ciclo encravado reinicia o módulo, todos os relés desligados) | Uma compilação de depuração | Bancada (HW2) |

## 13. Resolução de problemas

| Sintoma | Causa provável | O que fazer |
| --- | --- | --- |
| Um relé estala ao arrancar ou durante a gravação | Uma placa de disparo por nível baixo, um jumper de disparo em baixo, ou uma pull-down em falta | Usa uma placa de disparo por nível alto; confirma os 10 kohm de cada IN à massa ([secção 7](#7-relés-ou-estado-sólido)) |
| Nada liga | O fusível de entrada, o 1N5819 ao contrário, a bateria invertida, o buck por acertar | Confirma o fusível, a risca do díodo (para o buck) e os 5,0 V do buck |
| O LED pisca depressa e a caixa nunca encontra o módulo | O firmware recusou a sua lista de canais | Volta a compilar com um `OUTPUT_CHANNELS` válido ([README do firmware](../../firmware/output-module/README.md#the-channel-list)) |
| A caixa não encontra o módulo | O cabo, o pino 1 do M12 a cerca de 3,0 V no módulo, o endereço (0x5C-0x5F), pull-ups do lado 1 deixadas no isolador, o nível baixo do isolador ([secção 5](#5-os-dois-lados-o-isolador)) | Mede o VCC1; repete a 11.1 |
| O teclado ou o leitor NFC da caixa param quando o módulo é ligado | O lado 1 do isolador a prender o barramento, ou as suas pull-ups somadas às da caixa | Tira as pull-ups do lado 1; reporta o traçado do osciloscópio numa issue |
| Os contactos de um relé colam ou queimam | Uma carga indutiva sem díodo de roda livre, ou uma carga acima de 2 A | Monta o díodo em paralelo com a carga; confirma a corrente e o fusível da carga |
| Uma saída desliga-se sozinha passado algum tempo | O tempo máximo ligado do canal (o do módulo, ou o mais baixo da caixa), ou a concessão (a caixa deixou de escrever: `LEASE_EXPIRED`) | Esperado: os limites estão a fazer o seu trabalho; só sobe o tempo máximo ligado do módulo dentro do que o manual do aparelho permite |
| Um canal recusa voltar a ligar | O seu tempo mínimo desligado depois de um tempo máximo ligado, ou um relé a quem se pediu que comutasse em menos de 100 ms | Esperado; a reconciliação da caixa volta a tentar numa leitura seguinte |

---

Licença: este guia é CC-BY-SA-4.0; o desenho do módulo é CERN-OHL-S-2.0, como
o resto do hardware ([LICENSING.md](../../LICENSING.md)).
