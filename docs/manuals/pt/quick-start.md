<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Início rápido

Uma página para o dia do jogo. Em inglês: [Quick start](../en/quick-start.md). Cada função tem um manual completo: [quem joga](player.md), [organização](game-master.md), [marshal](marshal.md), [operação da Field Box](field-box.md).

> **Pré-alfa.** Nada disto foi usado num campo a sério. As palavras em *itálico* estão no [glossário](https://atalaia-project.link/glossario/).

## Se jogas

1. Instala a app Atalaia (Android 8.0 ou mais recente, ou iPhone). Toca na **roda dentada** e em **Língua** › a que preferires.
2. Liga-te ao Wi-Fi do campo. Se o telemóvel disser «sem internet», fica ligado.
3. **Participante › Check-in no campo › Ler o cartaz.** Lê o aviso, escreve o teu **Nome ou alcunha** e toca em **Fazer o check-in**.
4. **Escolhe as réplicas** que vais usar. Leva-as a um marshal para a *cronografagem*.
5. **Segue o jogo.** Captura as caixas na caixa: **mantém premido o botão da tua equipa** até a barra encher.
6. Opcional: **Partilhar a minha posição**. Deixa **Vibrar nos eventos do jogo** ligado.

## Se diriges o jogo

1. Arranca o controlador de campo (um Raspberry Pi com o modem USB, ou **Controlador de campo** na app, em Android). Obtém o **código da organização**: `python3 -m atalaia_controller tokens`.
2. Abre `http://` *endereço do controlador* `:8080/console/`. Escreve o código da organização.
3. Uma vez: **Definições** › escolhe o canal de rádio. **Adotar** as caixas novas. **Check-in** › **Imprimir o cartaz** e afixa-o.
4. **Jogo** › nome, modo, equipas, duração › **Criar jogo**.
5. **Convidar caixas**: marca-as, dá-lhes papéis, **Convidar**. Espera por **Tudo pronto para começar**.
6. **Check-in**: confirma quem joga, dá equipas, acrescenta marshals.
7. **Começar** › **Sim**. Vigia o **Registo** e as **Caixas**. **Terminar** no fim.

## Se és marshal

1. Faz o check-in como participante. Pede à organização que te acrescente em **Check-in › Marshals**.
2. **Marshal** mostra **O teu identificador de marshal é M-01**. Fica no Wi-Fi do campo pelo menos de 2 em 2 horas.
3. **Réplicas por cronografar** › toca numa réplica › **Entrada** › escolhe o **Peso da BB**, escreve a velocidade e **Registar o disparo** em cada disparo.
4. **Enviar ao controlador**. Durante o jogo, usa **Verificação**.

## Se cuidas das caixas

1. Antena montada. Bateria carregada. Interruptor **ligado**.
2. Na primeira vez: liga-te ao Wi-Fi `atalaia-…`, abre `192.168.4.1`, preenche a página e escolhe um **Admin PIN**.
3. A organização **adota** a caixa (cabo, cartão de campo ou código de 6 algarismos). Mostra **PRONTA · Próximo jogo**.
4. Convida-a. Mostra **À ESPERA** e depois **JOGO EM CURSO** no arranque.
5. Caixa perdida? A consola diz **sem notícias**. Aproxima-a, ou põe uma caixa no meio.

Montar uma caixa: o [guia de montagem](https://atalaia-project.link/montagem/).
