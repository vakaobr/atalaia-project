<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Guia de montagem do módulo de alvo (ainda não se pode montar)

Em inglês: [Target addon build guide](BUILD.md).

O módulo de alvo é uma placa a que se dispara, com um sensor que sente cada
impacto, e que se liga a uma caixa e a transforma num alvo com pontuação: o
hardware do modo *Janelas de Alvo*, em que um impacto enquanto o alvo mostra a
cor de uma equipa pontua para essa equipa.

> **Estado: o lado da caixa está decidido; o módulo não.** Desde 2026-10-23 a
> porta da caixa está especificada (só 3,3 V, quatro fios, sem linha de
> interrupção: a caixa interroga o módulo; decisões P5J-15 a P5J-21), e o
> firmware da Field Box tem um controlador de consulta testado para ela (um
> esqueleto, ainda não chamado). O módulo em si **ainda não se pode montar**: o
> seu processador não está escolhido, não existe firmware para ele, o seu
> endereço I2C e a sua resposta "identify" não estão decididos, e o sensor e a
> placa não estão desenhados (fase 4, fase HW2 do plano;
> [secção 5](#5-o-que-não-está-decidido)). Este guia diz o que está decidido,
> com a origem de cada decisão, e lista exatamente o que não está, para que
> ninguém monte algo que o firmware não vai suportar. **Não ligues uma placa a
> uma Field Box a partir desta página.** Quando o módulo for desenhado, esta
> página passa a ser o seu guia de montagem, com fotografias (fase HW2 do
> plano); este guia nunca usa fotografias de maquetas nem geradas.

## 1. O que está decidido

| O quê | Decidido | Onde |
| --- | --- | --- |
| Finalidade | Um alvo com pontuação de impactos para qualquer caixa | [Especificação de conceção](../../docs/design-spec.md), secção 6 |
| Peças, em resumo | Uma placa de aço ou de policarbonato, um sensor piezo, um processador pequeno (da classe RP2040 ou ATtiny) para detetar impactos. LED próprios só com uma alimentação própria ([secção 2](#2-a-porta-da-caixa)) | Especificação de conceção, secção 6; P5J-16 |
| Custo aproximado | 20-30 € em peças, a preços do mercado de amadores (não é um orçamento) | Especificação de conceção, secção 6 |
| Como se liga | Um conector **M12 de 5 pinos**, estanque, na caixa, com **só 3,3 V**: o trilho 3V3 da placa, GND, e o barramento I2C da caixa (SDA, SCL) a 3,3 V. **Sem 5 V na porta.** O quinto pino não está ligado. O módulo leva o seu próprio processador pequeno, que responde a um pedido "identify" com um descritor de capacidades, por isso a caixa não precisa de um controlador novo para cada módulo | Especificação de conceção, secção 6, "Addon bus" (corrigida em 2026-10-23); P5J-15, a seguir a M3 |
| Energia vinda da caixa | No máximo **25 mA** dos 3,3 V da porta, para o processador e o circuito do sensor, através de um fusível rearmável na caixa | P5J-16 |
| As luzes da janela | *Janelas de Alvo* acende o **anel de luzes da própria caixa** (`cap("ring")` em `modes/target_windows/node.lua`), por isso um módulo não precisa de LED. Um módulo com luzes próprias alimenta-as a partir da sua própria célula, nunca da porta | P5J-16 |
| Sem linha de interrupção | A caixa **interroga** o módulo por I2C a cada 20 ms; um impacto chega ao jogo em cerca de 21 ms ([secção 4](#4-como-a-caixa-lê-os-impactos-sem-linha-de-interrupção)). Não é preciso nenhum GPIO, por isso o mapa de pinos da Field Box não muda | P5J-18 |
| Cabo | I2C a 100 kHz em, no máximo, **2 m** de cabo M12 de 5 condutores; um alvo mais afastado usa antes um Satélite ou um nó fino pelo rádio | Especificação de conceção, secção 6; P5J-17 |
| O que os scripts de jogo da caixa veem | A capacidade `hit`: um evento `hit` com uma `strength` de 0 a 255 (os scripts recebem `hit.hit`), e os comandos `arm` e `disarm` (só comunica impactos enquanto armado) | Especificação de conceção, secção 7; rascunho do RFC 0000, Aditamento 1; decisão P4R4 |
| Como um impacto atravessa o fio (rascunho) | Um relatório de 5 bytes que a caixa lê (sinalizadores, o número de sequência do impacto, a sua força, a sua idade, um CRC-8) e três comandos que escreve (confirmar um impacto, armar, desarmar). O módulo guarda cada impacto até a caixa o confirmar, por isso nenhum se perde por o barramento estar ocupado | [`firmware/esp32/main/target_addon.h`](../../firmware/esp32/main/target_addon.h); P5J-19 |
| Num módulo de E/S de um telemóvel | A mesma capacidade `hit` no protocolo de proxy de capacidades (`{"id": "hit", "type": "hit"}`), com vetores de teste partilhados `target_addon`, `target_hit` e `target_arm`, para que um módulo de E/S pudesse emprestar uma a um telemóvel. Nenhum módulo de E/S montado até agora tem uma | [protocol/capability-proxy.md](../../protocol/capability-proxy.md), "A hit sensor" |
| O modo de jogo | *Janelas de Alvo* (`modes/target_windows/`): o papel `target` precisa de `hit` e `led`. O alvo fica escuro durante `interval_s`, depois acende a cor de uma equipa ao acaso durante `window_s`; um impacto de pelo menos `min_strength` na janela dá `hit_points` a essa equipa. Construído e testado no simulador; não é uma predefinição da Field Box enquanto o módulo não existir | [Plano da fase 4](../../docs/phase-4-site-server/PLAN.md), fase 2 do plano; decisões M2-1 a M2-5 |
| O que vem a seguir | O processador do módulo e o seu firmware, o controlador de consulta chamado a partir do ciclo de jogo da caixa, a capacidade `hit` no firmware da Field Box, o limiar e o debounce do sensor afinados em placas de aço e de policarbonato; depois *Janelas de Alvo* passa a ser uma predefinição integrada | Plano da fase 4, HW2 |

## 2. A porta da caixa

A porta é o barramento I2C da caixa levado para fora por um conector, por isso
segue as regras que todos os módulos I2C da Field Box já seguem: alimentada a
partir do 3V3 da placa, nunca a partir de 5 V, e nada puxa SDA ou SCL acima de
3,3 V (decisão M3, confirmada por quem mantém o projeto em 2026-10-21; o
[manual de montagem da Field Box, secção 9.2](../field-box/BUILD.pt.md); o "powered from 3V3, never 5V" do
expansor do teclado na
[lista de peças](../field-box/README.md#bill-of-materials-per-box)).

| Pino M12 (codificação A, 5 pinos) | Cor habitual do fio | Sinal | Na caixa |
| --- | --- | --- | --- |
| 1 | castanho | 3,3 V | O trilho 3V3 da placa de interligação, através de um fusível rearmável (PTC, cerca de 50 mA de retenção) |
| 2 | branco | SDA | O trilho SDA (GPIO 17 da placa) |
| 3 | azul | GND | O trilho GND |
| 4 | preto | SCL | O trilho SCL (GPIO 18 da placa) |
| 5 | cinzento | não ligado | Livre nas duas pontas, e nunca 5 V. Uma caixa futura com um GPIO de sobra poderia fazer dele uma linha de interrupção |

**Referência de pinos da porta.** A porta não usa nenhum GPIO próprio. É o
barramento I2C e os trilhos da caixa, por isso segue a
[referência de pinos da Field Box](../field-box/BUILD.pt.md#15-referência-de-pinos) (secção 15):

| Sinal da porta | Pino da placa | Opção do firmware | Nível |
| --- | --- | --- | --- |
| 3,3 V | o pino 3V3 da placa, através do hub e de um fusível rearmável | -- | 3,3 V |
| SDA | GPIO 17 | `ATALAIA_NFC_SDA_PIN` | 3,3 V, 100 kHz |
| SCL | GPIO 18 | `ATALAIA_NFC_SCL_PIN` | 3,3 V |
| GND | o trilho GND do hub | -- | 0 V |

Verificado contra o firmware em 2026-10-28: o controlador de consulta
(`firmware/esp32/main/target_addon.c`) ainda não é chamado pela caixa e não tem
endereço I2C, por isso uma Field Box ainda não consegue falar com um módulo.
**Ainda não testado numa placa real**: a porta, o fusível e o cabo.

SDA e SCL estão nos pinos 2 e 4, em lados opostos do conector e não lado a lado
(decisão P5J-20). A porta espera pelo primeiro módulo: uma Field Box montada
hoje não precisa dela.

O lado do módulo, segundo as mesmas decisões:

- **Nada acima de 3,3 V em nenhum pino.** O processador do módulo funciona com
  os 3,3 V da porta; uma peça do seu lado que precise de mais produz isso a
  partir da sua própria alimentação, que nunca se liga à porta.
- **Sem resistências de pull-up em SDA nem SCL no módulo**: o barramento da
  caixa já as tem (P5J-17).
- **No máximo 25 mA** do pino 1 (P5J-16). Um processador da classe ATtiny e o
  circuito do piezo consomem alguns miliamperes; um RP2040 à velocidade máxima
  aproxima-se do limite, por isso tem de ser medido, ou funcionar mais devagar.
- **As suas luzes, se tiver, a partir da sua própria célula**: uma célula 1S
  protegida com o seu próprio fusível e conversor elevador, como no caminho da
  energia do Satélite, com o seu GND unido ao GND da porta; a sua alimentação
  nunca chega à porta (P5J-16).

### Porquê 25 mA

O regulador de 3,3 V da placa já alimenta a placa (o ESP32-S3 e o rádio: cerca
de 80-150 mA, com picos de 400-500 mA enquanto o Wi-Fi ou o rádio transmitem), o
TFT com a sua retroiluminação (40-100 mA), o PN532 (50-150 mA com o campo
ligado), e o expansor do teclado e o medidor (menos de 1 mA): cerca de 170-400
mA num jogo, com picos perto de 750 mA
([orçamento de energia da Field Box](../field-box/BUILD.pt.md), estimativas, não
medições). O anel de luzes, o amplificador e os LED dos botões estão no
conversor elevador de 5 V, não nos 3,3 V. O limite do próprio regulador não está
documentado aqui, e saber se aguenta o TFT e o leitor NFC continua a ser um item
**Verifica na primeira montagem** da Field Box. Por isso a porta promete só uma
parte pequena e fixa: 25 mA são cerca de 3 % desses picos, e o fusível impede que
um curto-circuito no cabo ou no conector deixe a caixa sem energia. Um só LED
WS2812 consome até 60 mA, por isso luzes na porta estão fora de questão.

## 3. Verificações na primeira montagem (a verificar)

- **Pull-ups e cabo.** A 100 kHz o barramento tem de subir em 1 µs. Com cerca de
  100 pF por metro de cabo, 2 m de cabo e os módulos da própria caixa somam
  cerca de 300 pF, o que exige as pull-ups do barramento da caixa, todas em
  paralelo, entre cerca de **1 kΩ e 3,9 kΩ** (1 kΩ mantém a corrente que um
  dispositivo tem de absorver abaixo de 3 mA). Mede-o com a caixa desligada e
  todos os módulos montados: SDA a 3V3 e SCL a 3V3, na escala de resistência do
  multímetro. Acima de 3,9 kΩ, monta um par de 2,2 kΩ de SDA e SCL ao trilho
  3V3 na placa de interligação. Depois verifica que o teclado, o leitor NFC e o
  medidor continuam a funcionar com o cabo e um módulo ligados.
- **O fusível.** Um curto-circuito entre os pinos 1 e 3 da porta não pode
  reiniciar a caixa.
- **Proteger o barramento num conector exterior** (estática de uma mão, água no
  conector): são prováveis pequenas resistências em série e díodos de proteção
  na porta; os seus valores não estão escolhidos.
- **A corrente do módulo**, contra os 25 mA.

## 4. Como a caixa lê os impactos (sem linha de interrupção)

A Field Box usa todos os oito GPIO da placa que estão livres de qualquer peça da
placa (3, 4, 6, 15, 16, 33, 47, 48;
[tabela de pinos](../field-box/README.md#peripheral-pins)), e o conector GNSS
guarda o 34 e o 38-42, por isso não há pino para uma linha de interrupção. Também
não precisa dele (decisão P5J-18):

- Todo o tráfego I2C da caixa, o do teclado incluído, já corre no seu ciclo de
  jogo, a cada 10 ms. Uma interrupção só seria notada no tique seguinte, por
  isso o melhor que daria seria um impacto em 10 ms; consultar a cada 20 ms dá-o
  em 20 ms, mais 0,56 ms para ler o relatório.
- **Tempo de barramento.** A 100 kHz um byte com a sua confirmação demora 90 µs.
  Uma consulta (o endereço e 5 bytes) demora cerca de **0,56 ms**: a cada 20 ms,
  cerca de **3 %** do barramento. Receber um impacto acrescenta uma confirmação
  de 2 bytes (0,28 ms). A leitura do teclado, a cada 10 ms, já usa cerca de
  18 %; o medidor (a cada 10 s) quase nada; o OLED da placa uns milissegundos
  quando a imagem muda.
- **Latência.** Um impacto chega ao script cerca de 10 ms depois de o módulo o
  sentir, em média, e em cerca de 21 ms no máximo, contra um objetivo de 50 ms:
  a luz e o som de um impacto parecem imediatos, e uma janela está aberta pelo
  menos 1 s (5 s por omissão), por isso 20 ms são no máximo 2 % dela; um BB
  demora 0,2-0,3 s a atravessar 20-30 m, de qualquer modo. Momentos mais lentos:
  uma consulta NFC (a cada 300 ms num jogo) pode prender o ciclo até cerca de
  200 ms quando o leitor demora a responder, e ler a etiqueta de quem joga
  durante mais tempo. Nessas alturas os impactos não se perdem: o módulo guarda-os,
  com a sua idade, até a caixa os recolher.
- As opções postas de lado: partilhar a linha INT do expansor do teclado (não
  está ligada, `ATALAIA_KP_INT_PIN` é -1, ligá-la também levaria um GPIO, e os
  oito pinos do expansor estão todos em uso), ou libertar um GPIO abdicando do
  som ou do botão 3, o que custaria uma funcionalidade a todas as caixas por 10
  ms.

O controlador (`firmware/esp32/main/target_addon.c`, testes no computador em
`firmware/esp32/test/test_target_addon.c`) consulta, recebe cada impacto uma só
vez (uma confirmação perdida não conta um impacto duas vezes), volta a enviar
`arm` e `disarm` até o relatório do módulo concordar, recusa relatórios com um
CRC errado, e dá o módulo por desaparecido após 25 leituras falhadas seguidas
(0,5 s). **Ainda por fazer**, para quando o endereço do módulo estiver decidido:
as leituras e escritas I2C nesse endereço (`hal_esp_i2c`), encontrar o módulo no
arranque e juntar `hit` às capacidades da caixa, chamar o controlador a partir
do ciclo de jogo e passar cada impacto ao script como `hit.hit` com a sua
`strength`, enviar-lhe os `cap("hit"):arm()` e `:disarm()` do script
(`command_dispatch.c`), e fazer de *Janelas de Alvo* uma predefinição (P4R23).

## 5. O que não está decidido

Cada um destes pontos precisa de uma decisão antes de alguém montar um módulo:

1. **O processador**: RP2040 ou ATtiny (a especificação nomeia os dois), dentro
   dos 25 mA, e o firmware que corre.
2. **O endereço I2C do módulo e a sua resposta "identify"** (o descritor de
   capacidades). O endereço tem de ficar longe dos dispositivos da caixa:
   0x20-0x27 e 0x38-0x3F (onde a caixa procura o expansor do teclado), 0x24
   (NFC), 0x36 (medidor) e 0x3C (OLED). O relatório do impacto e os comandos têm
   um **rascunho** ([secção 1](#1-o-que-está-decidido)) contra o qual os dois
   firmwares podem ser escritos; passa a definitivo com o primeiro módulo.
3. **As peças do conector e o fabricante do cabo**, e a proteção na porta
   ([secção 3](#3-verificações-na-primeira-montagem-a-verificar)).
4. **O circuito do sensor**: o elemento piezo, como é montado na placa (e
   isolado dela), a sua proteção e o andar de entrada analógico; o limiar e o
   debounce hão de ser afinados em placas a sério (HW2).
5. **A placa**: material e espessura, tamanho, o seu suporte e o ângulo a que é
   posta, e a caixa que protege o processador e o cabo.
6. **Luzes no próprio módulo**: não são precisas para *Janelas de Alvo*; se um
   desenho futuro as quiser, a sua própria célula, carregamento e caixa.

## 6. Segurança, quando houver algo para montar

Isto vale para qualquer alvo usado com airsoft ou paintball, seja qual for o
desenho:

- **Proteção dos olhos e da cara** para todas as pessoas ao alcance do alvo
  enquanto alguém lhe dispara, incluindo na bancada enquanto o sensor é afinado.
- **Ricochetes.** Os BB ressaltam numa placa dura, e alguns voltam para trás. Põe
  uma placa de aço num ângulo que os mande para o chão, nunca plana na direção
  de quem dispara. Nunca dispares contra a caixa, o cabo ou o
  conector, só contra a placa.
- **Protege a eletrónica.** O processador, as suas ligações e o cabo ficam atrás
  da placa ou na sua própria caixa, fora da linha de tiro.
- **Os limites de potência do campo** (o cronógrafo, o limite em joules)
  aplicam-se a disparar contra alvos como a disparar contra pessoas; o alvo não
  é motivo para os subir.
- **Um dispositivo de jogo**: cores vivas e uma etiqueta "GAME PROP", como todos
  os dispositivos da Atalaia; e a caixa a que se liga segue as regras de bateria
  do seu próprio guia de montagem
  ([Field Box](../field-box/BUILD.pt.md), secção 4,
  [Satélite](../satellite/BUILD.pt.md#4-ferramentas-e-segurança)), tal como a
  célula própria de um módulo, se a tiver.

## 7. Fotografias

<!-- PHOTO: target-addon-plate.jpg | the finished target: plate and sensor mounting, front and back -->
> **Fotografia a juntar depois da primeira montagem:** o alvo acabado, a placa e
> a montagem do sensor, frente e verso.

<!-- PHOTO: target-addon-port.jpg | the M12 addon port on a box, and the addon's cable plugged in -->
> **Fotografia a juntar depois da primeira montagem:** a porta M12 do módulo
> numa caixa, com o cabo do módulo ligado.

## 8. Ajudar

Se quiseres desenhar o módulo, abre primeiro uma issue ou uma discussão: as
decisões acima vêm antes de qualquer ligação, e o resto do lado do firmware
(chamar o controlador da porta, e a capacidade `hit` numa caixa) tem de ser
escrito com ele. Os projetos são CERN-OHL-S-2.0, como o resto do hardware
([LICENSING.md](../../LICENSING.md)).

---

Licença: este guia é CC-BY-SA-4.0.
