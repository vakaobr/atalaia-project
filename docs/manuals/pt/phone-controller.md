<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Guia do telemóvel controlador (Android)

Para quem na organização usa um **telemóvel Android como controlador de campo** de um jogo pequeno, sem Raspberry Pi. O telemóvel dirige o jogo, serve a consola da organização, o check-in e o marcador na rede Wi-Fi do campo, e fala com as caixas através de um rádio ligado a ele. Dirigir o jogo está no [Manual da organização](game-master.md). O controlador num Raspberry Pi está no [Guia de montagem do controlador](controller-setup.md); os dois fazem o mesmo trabalho, e este guia diz onde diferem. Em inglês: [Phone controller guide](../en/phone-controller.md).

> **Ainda não está pronto para o campo.** A Atalaia está em pré-alfa. A 2026-11-06 o telemóvel controlador já correu num computador e num emulador Android, contra o próprio código das caixas, do módulo de E/S e do modem; **ainda não num telemóvel a sério**, com um rádio a sério, nem num campo. Só Android: a app do iPhone não tem controlador.

Conteúdo: 1. O que é preciso · 2. Arrancar o controlador · 3. Códigos e a chave de entrada · 4. O relógio do controlador · 5. A rede · 6. O rádio: modem de rádio USB ou módulo de E/S · 7. Um controlador de reserva · 8. O que precisa de um computador · 9. Cópias de segurança e durante quanto tempo se guardam os dados · 10. Atualizações · 11. Resolução de problemas

<a id="1-what-you-need"></a>

## 1. O que é preciso

| Precisas de | Notas |
| --- | --- |
| Um telemóvel Android com a app Atalaia | Android 8.0 ou mais recente. A app ainda não está no Google Play: vem com cada [versão no GitHub](https://github.com/vakaobr/atalaia-project/releases) a partir da v0.9.0, e o [Manual de quem joga](player.md) diz como a instalar. Mantém o telemóvel carregado, ou ligado a um powerbank: é ele que corre o jogo todo |
| Um rádio para as caixas | Um **modem de rádio USB** (a placa modem do Pi, ligada ao USB do telemóvel) ou um **módulo de E/S** (por USB ou Bluetooth). Sem um deles, só jogam dispositivos de jogo Android por Wi-Fi. Qual escolher: [secção 6](#6-the-radio-usb-radio-modem-or-io-pod) |
| Uma rede Wi-Fi do campo | O hotspot do próprio telemóvel, um router, ou uma rede que a app cria para o jogo ([secção 5](#5-the-network)). Não precisa de internet |
| Um computador na rede Wi-Fi do campo | Para imprimir o cartaz de check-in e as etiquetas, e para exportar ([secção 8](#8-what-needs-a-computer)) |

<a id="2-start-the-controller"></a>

## 2. Arrancar o controlador

1. Na app, toca em **Controlador de campo**.
2. Se pedir, autoriza as notificações. Em **A otimização da bateria pode parar o controlador a meio de um jogo.**, toca em **Pedir a exceção**.
3. Em **Rede do campo**, escolhe como os telemóveis lhe chegam ([secção 5](#5-the-network)).
4. Liga **Aberto na rede Wi-Fi do campo**. Sem isto, só este telemóvel chega ao controlador.
5. Em **Rádio**, toca em **Procurar módulos** e escolhe na lista o teu modem de rádio USB ou módulo de E/S ([secção 6](#6-the-radio-usb-radio-modem-or-io-pod)). Escolhe o rádio antes de arrancar: para o mudar depois, pára o controlador.
6. Confirma a **Chave de entrada do campo** nas **Definições** (a roda dentada) ([secção 3](#3-codes-and-the-join-key)).
7. Toca em **Arrancar o controlador**. O telemóvel continua a correr com o ecrã apagado.
8. Em **Códigos de acesso**, toca em **Mostrar os códigos**.
9. Toca em **Abrir a consola**, ou abre num computador um dos endereços de **A consola, nos computadores da rede do campo:**.

Se parares e voltares a arrancar o controlador, um jogo em curso continua.

<a id="3-codes-and-the-join-key"></a>

## 3. Códigos e a chave de entrada

**Códigos de acesso.** Em **Códigos de acesso**, **Mostrar os códigos** mostra dois códigos:

- o **Código da organização** dirige o jogo. Não o mostres a quem joga;
- o **Código só de leitura (marcador)** só vê.

Para um árbitro ou uma organização convidada, cria um código do dia com prazo na consola (**Definições**, **Códigos de acesso temporários**; vê o [Manual da organização](game-master.md)) em vez de dares o código da organização.

**A chave de entrada do campo** é o segredo-mestre do campo: as caixas recebem-na quando são adotadas, e um controlador de reserva precisa da mesma. O telemóvel guarda-a nas **Definições**, em **Chave de entrada do campo**.

- Se não houver nenhuma quando arrancas o controlador pela primeira vez, a app cria uma e guarda-a lá.
- Para usar a chave de um campo que já existe (por exemplo, a do Pi), escreve lá os 64 algarismos hexadecimais dela antes de arrancar. Num Pi, o `join-key` mostra-a ([Guia de montagem do controlador, secção 5](controller-setup.md#5-primeiro-arranque-códigos-e-chaves)).
- Depois, a app só mostra os últimos algarismos da chave, nunca a chave inteira. Se quiseres uma cópia (para um controlador de reserva, ou para o caso de perderes o telemóvel), cria tu a chave, escreve-a lá e guarda a cópia num sítio seguro.

**Cartão de campo.** Em **Cartão de campo**, **Escrever o cartão de campo** escreve a chave de entrada num cartão NTAG215 ou NTAG216 com o NFC do telemóvel; as caixas novas entram no campo quando lhes encostas o cartão. A app avisa primeiro: quem tiver esse cartão consegue fazer cartões de entrada para as tuas caixas. Guarda-o fechado à chave.

<a id="the-controller-clock"></a>

## 4. O relógio do controlador

**A partir da v0.9.0** o telemóvel controlador tem a guarda do relógio do Raspberry Pi. A hora de um telemóvel costuma estar certa, dada pela rede móvel, mas pode estar errada num telemóvel que foi reposto, acertado à mão ou que esteve muito tempo sem rede.

1. O controlador compara o relógio com o dia em que esta versão do programa foi publicada, com a hora mais recente que já viu e com os dados mais recentes que guarda.
2. Se o relógio estiver antes, a consola mostra em todos os ecrãs a faixa amarela **O relógio do controlador está errado.**, e nada é apagado enquanto não estiver certo.
3. Para o acertar, abre a consola num dispositivo com a hora certa e, na faixa ou em **Definições › Relógio do controlador**, toca em **Acertar o relógio do controlador por este dispositivo** (só com o código da organização). Só **avança**.
4. O acerto dura até o controlador parar. O controlador usa a hora acertada quando diz a hora às caixas e quando envia **Libertar todas as caixas que não estão neste jogo**.

Os jogos e os temporizadores nunca dependem do relógio. Porque é que o relógio importa e o que a guarda faz está no [Guia de montagem do controlador](controller-setup.md#the-controller-clock).

<a id="5-the-network"></a>

## 5. A rede

Em **Rede do campo**, escolhe uma:

1. **O hotspot do próprio telemóvel.** Toca em **Definições do hotspot** e liga-o. Guarda o nome e a palavra-passe: vão no cartaz de check-in.
2. **Um router a que o telemóvel se liga.** Toca em **Definições de Wi-Fi** e liga-te a ele. O router tem de funcionar sem internet e não pode isolar os clientes: as mesmas regras que para um Pi, no [Guia de montagem do controlador, secção 8](controller-setup.md#usar-um-router-de-viagem).
3. **Criar uma rede para o jogo.** O Android escolhe um nome e uma palavra-passe novos de cada vez. Quem joga entra com o código QR que está no ecrã. Não os ponhas no cartaz.

Depois liga **Aberto na rede Wi-Fi do campo**. Telemóveis, computadores e dispositivos de jogo ligam-se por HTTPS (porta 8443, com a autoridade de certificação do próprio campo) e por MQTT sobre TLS (porta 8883).

**Nomes TLS.** Não há `tls_names` para definir: o telemóvel põe no certificado do campo os seus próprios endereços e os endereços guardados no cartaz de check-in. O ecrã mostra a **Impressão digital da CA do campo**, que o cartaz leva. Se o endereço do telemóvel mudar (outro router, outro hotspot), imprime o cartaz outra vez.

**O nome do Wi-Fi do campo no cartaz.** Na consola, separador **Check-in**, formulário **Cartaz de check-in**, **Nome da rede Wi-Fi do campo**.

<a id="6-the-radio-usb-radio-modem-or-io-pod"></a>

## 6. O rádio: modem de rádio USB ou módulo de E/S

Os dois levam o rádio do jogo. Diferem no resto:

| | Modem de rádio USB | Módulo de E/S |
| --- | --- | --- |
| O que é | A placa modem do Pi ([Montar o modem de rádio](modem.md)) | Uma placa de módulo com botões, luzes, sirene e leitor NFC também |
| Ligação ao telemóvel | Só USB (um cabo de dados OTG) | USB (preferível) ou Bluetooth |
| Jogos com caixas | Sim | Sim |
| Convites, fim de jogo, emparelhamento por código | Sim | Só com um firmware do módulo que passe estas tramas; com um módulo antigo a consola diz que o rádio não as leva |
| Atualizações de firmware das caixas | Sim | Sim |
| Procura de canal | Sim | Sim |
| Caixas presas num jogo terminado avisadas e libertadas sozinhas | Sim, com uma imagem do modem da v0.9.0 | **Não**: um módulo de E/S não as consegue avisar |
| Botões, luzes, sirene para o telemóvel | Não | Sim |

Para usar um modem de rádio USB, segue [Montar o modem de rádio, Com um telemóvel controlador](modem.md#with-a-phone-controller). Ligar um módulo de E/S (a chave de acesso por Bluetooth, voltar a ligar) está no [Guia do telemóvel como dispositivo de jogo](phone-prop.md).

Quando o rádio não consegue avisar das caixas presas num jogo terminado, o ecrã di-lo em **Rádio**: *O firmware deste modem de rádio USB não consegue dizer que caixas ficaram num jogo terminado: atualiza-o...* ou *Um módulo de E/S não consegue dizer que caixas ficaram num jogo terminado...*. Até lá, tira essa caixa do jogo na própria caixa ([manual da Field Box](field-box.md#take-a-box-out-of-its-game)).

O telemóvel não adota caixas por cabo USB. Adota-as com o **cartão de campo** ou pelo **código de emparelhamento** (separador **Adotar** da consola).

<a id="standby-controller"></a>

## 7. Um controlador de reserva

Um telemóvel pode ficar de reserva para um Pi, e um Pi para um telemóvel. Como um controlador de reserva entra num jogo, o que recusa e como assume está no [Guia de montagem do controlador, Um controlador de reserva](controller-setup.md#standby-controller). No telemóvel:

1. Dá-lhe a **mesma chave de entrada do campo** que o controlador principal ([secção 3](#3-codes-and-the-join-key)).
2. Nas **Definições**, abre **Servidor do site, substituição e ATAK (controlador de campo)**. Em **Substituição**, escolhe **Manual** ou **Automático**. *Manual: o GM promove um controlador de reserva. Automático: um controlador de reserva assume depois de três sinais em falta (30 s).* Um de reserva conta os sinais que ouve do controlador principal, por isso, atrás de um principal em manual, espera cerca de 90 s e não assume o jogo de um controlador que ainda funciona ([Guia de montagem do controlador](controller-setup.md#failover-mode)). Mesmo assim, dá a mesma escolha a todos os controladores de um jogo: o separador **Controlador** da consola avisa quando são diferentes.
3. A definição vale quando o controlador arrancar outra vez: pára-o e volta a arrancá-lo.
4. Entra em cada jogo como controlador de reserva pelo separador **Juntar** da consola, **Entrar como controlador de reserva**, com o texto que o controlador principal gerou.
5. Para assumir à mão, toca em **Promover a controlador** no separador **Controlador** da consola.

**Energia.** Um telemóvel controlador conta sempre como se estivesse a uma bateria pequena. Quando um telemóvel e um Pi ligado à corrente se candidatam os dois, **o telemóvel cede ao Pi**. Não há definição para isto no telemóvel.

<a id="8-what-needs-a-computer"></a>

## 8. O que precisa de um computador

A consola dentro da app não imprime nem guarda ficheiros. Abre a consola no navegador de um computador, num dos endereços de **A consola, nos computadores da rede do campo:**, para:

- **o cartaz de check-in** (separador **Check-in**, **Imprimir o cartaz**). O cartaz precisa do controlador aberto na rede Wi-Fi do campo;
- **as etiquetas das réplicas** (**Imprimir etiquetas**);
- **Exportar CSV** da lista de check-in.

Tudo o resto funciona na consola da própria app.

<a id="9-backups-and-how-long-data-is-kept"></a>

## 9. Cópias de segurança e durante quanto tempo se guardam os dados

O telemóvel controlador guarda os jogos, os códigos, a autoridade de certificação do campo e as definições no armazenamento privado da app. **Não há comando de cópia de segurança.** Se a app for removida ou o telemóvel se perder, perdem-se:

- guarda uma cópia da chave de entrada do campo ([secção 3](#3-codes-and-the-join-key)): com ela, um telemóvel novo ou um Pi fica com as caixas do campo sem as adotar outra vez;
- quem joga lê o cartaz novo e volta a confiar no campo, porque o certificado é novo;
- as caixas que estavam num jogo quando o telemóvel se perdeu podem ficar presas nele: o [Manual da organização](game-master.md#recover-from-problems) diz como as libertar.

**Retenção.** Os mesmos prazos que num Pi: os eventos e as pontuações de um jogo terminado 90 dias, as leituras do cronógrafo 365 dias, os nomes e os números de federado 30 dias depois do jogo. Os dois primeiros definem-se na consola, **Check-in › Regras do check-in**. Nada é apagado enquanto o relógio estiver errado (a partir da v0.9.0). A tabela está no [Guia de montagem do controlador](controller-setup.md#how-long-the-controller-keeps-data).

**Servidor do site.** Nas **Definições**, **Servidor do site, substituição e ATAK (controlador de campo)**, o telemóvel recebe o endereço do servidor do site do campo e a chave da API, como o `[sync]` de um Pi. **Enviar as chegadas sem inscrição ao servidor do site como convidados** é o `push_walkins` do Pi: lê o [Manual da administração do site](site-admin.md) antes de o ligares.

<a id="10-updates"></a>

## 10. Atualizações

**A app.** Descarrega o `atalaia-app-<versão>.apk` da [versão no GitHub](https://github.com/vakaobr/atalaia-project/releases) (a partir da v0.9.0; se quiseres, confere-o com o `.apk.sha256` ao lado) e instala-o por cima do antigo, entre jogos. A partir da v0.9.0, todos os APK das versões são assinados com a única chave Android do projeto ([a sua impressão digital](../../community/keys.md#the-android-app), em inglês), por isso o Android instala-o por cima e mantém os dados da app: os jogos, os códigos, a chave de entrada, o certificado e as definições do controlador.

**Só uma vez, antes do primeiro APK de uma versão: faz cópia, depois desinstala.** Uma app instalada de um `atalaia-debug.apk` (todas as cópias anteriores à v0.9.0, ou uma que tenhas compilado tu) está assinada com a chave do computador que a compilou, e o Android recusa instalar o APK da versão por cima dela. Tem de ser desinstalada uma vez, e **desinstalar apaga tudo o que está na secção 9**: os jogos com as pontuações e os eventos, os códigos de acesso, a chave de entrada do campo, a autoridade de certificação do campo, a lista de check-in e todas as definições. Faz isto entre dias de jogo, nunca num, e por esta ordem:

1. Antes do dia, confirma que tens a **chave de entrada do campo**. A app nunca mostra a chave inteira: se a escreveste tu, usa a tua cópia (ou o `join-key` do Pi). Se foi a app que a fez e não tens cópia, as caixas terão de ser adotadas de novo depois da mudança ([Manual da Field Box](field-box.md)).
2. Aponta as outras definições que mudaste (Wi-Fi do campo, rádio, endereço e chave de API do servidor do site, chaves das versões do firmware, prazos de conservação) e exporta da consola o que quiseres guardar (o **Exportar CSV** da lista de check-in precisa de um computador: [secção 8](#8-what-needs-a-computer)). Termina primeiro todos os jogos, para nenhuma caixa ficar num.
3. Desinstala a Atalaia, instala o APK da versão, escolhe **Controlador de campo**, escreve a chave de entrada nas **Definições** antes de arrancares o controlador e volta a definir o resto.
4. A app faz códigos de acesso novos e um certificado novo: dá o código novo à organização do jogo, imprime o cartaz de check-in novo, e quem joga confia no campo outra vez.

A partir daí, todas as atualizações se instalam por cima. Nunca desinstales para atualizar outra vez: se o Android alguma vez recusar o APK de uma versão, para e pergunta primeiro nas issues do projeto.

**v0.11.0: só a app.** Vindo da v0.10.0, instala o APK da v0.11.0 quando te der jeito (instala-se por cima da v0.9.0 ou seguinte e mantém os dados da app); as caixas e o modem não têm de mudar com ela. A partir da v0.11.0, o telemóvel controlador mostra à equipa se um check-in na app veio do **telemóvel da inscrição** ou do **telemóvel por provar**, quando o servidor do site e a app de quem joga também estiverem na v0.11.0 ([manual de marshal](marshal.md#bilhetes-impressos-e-inscrições)). Vindo da v0.9.0 ou anterior, continua a valer a regra da v0.10.0 abaixo.

**v0.10.0: a app, as caixas e o modem ao mesmo tempo.** A partir da v0.10.0, **Libertar todas as caixas que não estão neste jogo** indica o canal, e uma caixa v0.9.0 e um controlador v0.10.0, ou o contrário, não aceitam o dela um do outro. Instala o APK da v0.10.0 (instala-se por cima da v0.9.0 e mantém os dados da app), atualiza todas as caixas para a v0.10.0 no mesmo dia e grava de novo o modem de rádio USB com a imagem da v0.10.0.

**O rádio.** Um modem de rádio USB atualiza-se por USB a partir de um computador: [Montar o modem de rádio, Atualizar o modem](modem.md#update-the-modem). Um módulo de E/S: [Guia do telemóvel como dispositivo de jogo](phone-prop.md).

**As caixas.** Em **Atualizações de firmware**, **Chaves das versões de firmware** lista as chaves cujas versões o telemóvel aceita (uma por linha, 44 caracteres cada), como o `[firmware] release_keys` do Pi. Um telemóvel que tinha o valor por omissão anterior do projeto passa sozinho para as chaves novas; uma lista que escreveste à mão fica como está. Desde a v0.8.0, as chaves do projeto são:

```
5tzPkN0AJSn+g34CP59linCRf/fcaWFc7GAAg7qzYNc=
76eY5BoMQ4RHohhX/8iSUlIUA5o5Entfk7EFBUxpbSY=
```

Tira `rIO8ogMU3LRLLtnt6Rys+URdKYfmNv5mxvuRJQsX9Tw=` (retirada a 2026-11-04) se a escreveste. Um controlador a correr reinicia para ficar com as chaves. As caixas vão buscar a versão por HTTPS ao telemóvel, por isso **Aberto na rede Wi-Fi do campo** tem de estar ligado. A atualização em si está no [manual da Field Box](field-box.md#update-the-boxes).

<a id="11-troubleshooting"></a>

## 11. Resolução de problemas

| Problema | O que fazer |
| --- | --- |
| O controlador pára quando o ecrã se apaga | Autoriza as notificações e toca em **Pedir a exceção** no aviso da bateria. Se o Android disser *O Android não deixou abrir a notificação do controlador*, deixa a app aberta |
| **Nenhum módulo encontrado.** em **Rádio** | USB: um cabo de dados (não só de carga) e um adaptador OTG se o telemóvel precisar. Bluetooth: o módulo ligado e perto. Um modem de rádio USB aparece na mesma lista |
| **Para mudar o rádio, para o controlador.** | O rádio escolhe-se antes de **Arrancar o controlador**: pára-o, escolhe o rádio e arranca outra vez |
| Os telemóveis não abrem a consola nem fazem check-in | **Aberto na rede Wi-Fi do campo** está desligado, ou os telemóveis estão noutra rede, ou o router isola os clientes ([secção 5](#5-the-network)) |
| *Este telemóvel não está em nenhuma rede Wi-Fi* | Liga o hotspot, junta-te ao router do campo, ou cria uma rede para o jogo |
| *O cartaz de check-in precisa do controlador aberto na rede Wi-Fi do campo.* | Liga **Aberto na rede Wi-Fi do campo** e imprime o cartaz num computador |
| Uma faixa amarela diz **O relógio do controlador está errado.** | Acerta-o a partir de um dispositivo com a hora certa (secção 4) |
| O ecrã diz que o rádio não consegue avisar das caixas presas num jogo terminado | Com um módulo de E/S: usa um modem de rádio USB para isso. Com um modem: atualiza-o (secção 10). Até lá, tira a caixa do jogo na própria caixa ([manual da Field Box](field-box.md#take-a-box-out-of-its-game)) |
| *Nenhuma: este controlador não aceita versões de firmware para as caixas.* | Põe as chaves do projeto em **Chaves das versões de firmware** (secção 10) |
| As definições de **Servidor do site, substituição e ATAK** não fazem nada | Valem quando o controlador arrancar outra vez: pára-o e volta a arrancá-lo |

Encontraste um passo que não corresponde? Abre uma issue ou diz-nos nas [Discussions](https://github.com/vakaobr/atalaia-project/discussions).
