<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Início rápido

Uma página para o dia do jogo. Em inglês: [Quick start](../en/quick-start.md). Cada função tem um manual completo: [quem joga](player.md), [organização](game-master.md), [marshal](marshal.md), [operação da Field Box](field-box.md), [telemóvel como dispositivo de jogo](phone-prop.md). Todos os manuais: [o índice](../README.md).

> **Pré-alfa.** Nada disto foi usado num campo a sério. As palavras em *itálico* estão no [glossário](https://atalaia-project.link/glossario/).

## Se jogas

1. Instala a app Atalaia (Android 8.0 ou mais recente, ou iPhone). Toca na **roda dentada** e em **Língua** › a que preferires.
2. Liga-te ao Wi-Fi do campo. Se o telemóvel disser «sem internet», fica ligado.
3. **Participante › Check-in no campo › Ler o cartaz.** Lê o aviso, escreve o teu **Nome ou alcunha** e toca em **Fazer o check-in**. Inscreveste-te online? Escolhe a tua inscrição em **Inscrição online**, ou mostra o bilhete impresso a um marshal ou na receção.
4. **Escolhe as réplicas** que vais usar. Leva-as a um marshal para a *cronografagem*.
5. **Segue o jogo.** Captura as caixas na caixa: **mantém premido o botão da tua equipa** até a barra encher.
6. Opcional: **Partilhar a minha posição**. Deixa **Vibrar nos eventos do jogo** ligado.

## Se diriges o jogo

1. Arranca o controlador de campo. Num Raspberry Pi, mostra os códigos com `cd /opt/atalaia/controller && sudo -u atalaia python3 -m atalaia_controller tokens --config /etc/atalaia/controller.toml`. Num telemóvel Android, abre **Controlador de campo** na app e depois **Códigos de acesso › Mostrar os códigos**.
2. Abre `https://` *endereço do controlador* `:8443/console/` (aceita uma vez o certificado do próprio campo). Escreve o **código da organização**.
3. Uma vez: **Definições** › escolhe o canal de rádio. **Adotar** as caixas novas. **Check-in** › **Imprimir o cartaz** e afixa-o.
4. **Jogo** › nome, modo, equipas, duração › **Criar jogo**.
5. **Convidar caixas**: marca-as, dá-lhes papéis, **Convidar**. Espera por **Tudo pronto para começar**.
6. **Check-in**: confirma quem joga, dá equipas, acrescenta marshals. Quem tem inscrição aparece como **por chegar**: toca em **Chegou**, ou lê o bilhete em **Bilhete impresso**.
7. **Começar** › **Sim**. Vigia o **Registo** e as **Caixas**. **Terminar** no fim.

Firmware novo para as caixas: [Atualizar as caixas](field-box.md#update-the-boxes).

## Se és marshal

1. Faz o check-in como participante. Pede à organização que te acrescente em **Check-in › Marshals**.
2. **Marshal** mostra **O teu identificador de marshal é M-01**. Fica no Wi-Fi do campo pelo menos de 2 em 2 horas.
3. Na receção: compara os cartões de filiação e toca em **Cartão visto, confere**; faz o check-in de quem não tem a app com **Check-in à mão**. Aceita o bilhete impresso de quem se inscreveu em **Marshal › Check-in com bilhete** ([a receção](marshal.md#2-a-receção)).
4. **Réplicas por cronografar** › toca numa réplica › **Entrada** › escolhe o **Peso da BB**, escreve a velocidade e **Registar o disparo** em cada disparo.
5. **Enviar ao controlador**. Durante o jogo, usa **Verificação**.

## Se cuidas das caixas

1. Antena montada. Bateria carregada. Interruptor **ligado**.
2. Na primeira vez: liga-te ao Wi-Fi `atalaia-…`, abre `192.168.4.1`, preenche a página e escolhe um **Admin PIN**. A palavra-passe do Wi-Fi do campo tem de ficar vazia, ter 8 a 63 caracteres ou 64 algarismos hexadecimais.
3. A organização **adota** a caixa (cabo, cartão de campo ou código de 6 algarismos). Mostra **PRONTA · Próximo jogo**.
4. A organização convida-a. Mostra **À ESPERA** e depois **JOGO EM CURSO** no arranque.

## Se alguma coisa correr mal

- **Uma caixa é recusada «noutro jogo», ou a consola mostra-a em Presas num jogo terminado:** toca em **Libertar**; ou tira-a do jogo na própria caixa ([tirar uma caixa do jogo](field-box.md#take-a-box-out-of-its-game), a partir da v0.9.0, ainda não publicada). Mais: [recuperar de problemas](game-master.md#recover-from-problems).
- **A consola diz Rádio em baixo:** verifica o cabo do modem USB e vê [recuperar de problemas](game-master.md#recover-from-problems) e [atualizar o modem](modem.md#update-the-modem).
- **Uma faixa amarela diz O relógio do controlador está errado:** toca em **Acertar o relógio do controlador por este dispositivo** se a hora do teu telemóvel estiver certa ([o relógio do controlador](controller-setup.md#the-controller-clock)).
- **Uma caixa aparece sem notícias:** aproxima-a, ou põe uma caixa no meio; depois de mudar de canal, usa **Procurar caixas** ([mudar de canal](game-master.md#change-the-channel)).
- **A consola não abre:** usa `https://` e a porta `8443`, fica no Wi-Fi do campo e confirma o código; um código temporário pode ter expirado ([recuperar de problemas](game-master.md#recover-from-problems)).

Montar uma caixa: o [guia de montagem](https://atalaia-project.link/montagem/).
