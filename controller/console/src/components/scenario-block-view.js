// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The scenario builder's block view (phase 5 plan phase 7, decisions P5F-*): a Blockly workspace
// over the blocks of scenario-blocks.js. It starts from a Blockly state (made from the manifest
// the controller read, or kept across a language change), and on every change made by the GM it
// hands the builder the YAML the blocks write and the problems only the blocks have. The builder
// keeps the YAML as its text, so the controller's checks, the draft and Install work as before.
// Blockly owns this component's element: Preact renders it once.

import { html, Component, t, lang } from '../ui.js';
import {
    blockForPath, defineBlocks, loadBlockly, MEDIA, RENDERER, THEME, toolbox, toYaml, workspaceToManifest,
} from './scenario-blocks.js';

const NARROW = 640; // px: under this the categories go above the blocks
const PROBLEM_CLASS = 'scn-problem';

const tb = (key) => t(`scenario_blocks.blocks.${key}`);

/** One theme name in light and dark: the name is part of the renderer's stylesheet, whose hash
 * the Content-Security-Policy allows (decision P5F-2). */
function theme(B) {
    const dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    return B.Theme.defineTheme(THEME, {
        base: B.Themes.Classic,
        componentStyles: dark ? {
            workspaceBackgroundColour: '#121614',
            toolboxBackgroundColour: '#1b211d',
            toolboxForegroundColour: '#e6ece6',
            flyoutBackgroundColour: '#222a25',
            flyoutForegroundColour: '#e6ece6',
            flyoutOpacity: 1,
            scrollbarColour: '#55605a',
        } : {
            workspaceBackgroundColour: '#fbfcfa',
            toolboxBackgroundColour: '#eef2ec',
            toolboxForegroundColour: '#1d231f',
            flyoutBackgroundColour: '#e3e9e1',
            flyoutForegroundColour: '#1d231f',
            flyoutOpacity: 1,
        },
    });
}

export class ScenarioBlocks extends Component {
    constructor() {
        super();
        this.host = null;
        this.ws = null;
        this.where = {};
        this.local = [];
        this.marked = new Set();
        this.problems = [];
        this.timer = null;
    }

    componentDidMount() {
        this.start().catch((e) => this.props.onError && this.props.onError(e));
    }

    shouldComponentUpdate(next) {
        this.problems = next.problems || [];
        this.mark();
        return false;
    }

    componentWillUnmount() {
        this.stopped = true;
        clearTimeout(this.timer);
        if (this.ws) {
            // Kept for the next view (a language change re-creates the blocks with its texts).
            this.props.store.state = window.Blockly.serialization.workspaces.save(this.ws);
            this.ws.dispose();
            this.ws = null;
        }
    }

    async start() {
        const B = await loadBlockly(lang());
        if (this.stopped) return;
        defineBlocks(B, tb);
        const narrow = this.host.clientWidth < NARROW;
        this.ws = B.inject(this.host, {
            toolbox: toolbox(tb),
            media: MEDIA,
            renderer: RENDERER,
            theme: theme(B),
            sounds: false,
            comments: false, // a comment's bubble sets an inline style, which the CSP refuses
            trashcan: true,
            horizontalLayout: narrow,
            toolboxPosition: 'start',
            move: { scrollbars: true, drag: true, wheel: false },
            zoom: { controls: true, wheel: false, startScale: narrow ? 0.7 : 0.85 },
        });
        B.Events.disable(); // loading is not an edit: the YAML (and its comments) stays as it is
        try {
            B.serialization.workspaces.load(this.props.store.state, this.ws);
        } finally {
            B.Events.enable();
        }
        this.generate(false);
        this.ws.addChangeListener((e) => {
            if (e.isUiEvent) return;
            clearTimeout(this.timer);
            this.timer = setTimeout(() => this.generate(true), 0); // one regeneration per burst of events
        });
        if (this.props.onReady) this.props.onReady();
    }

    /** The manifest the blocks say; with send, its YAML goes to the builder. */
    generate(send) {
        if (!this.ws) return;
        const { manifest, where, problems } = workspaceToManifest(this.ws);
        this.where = where;
        this.local = problems;
        if (send && manifest) this.props.onChange(toYaml(manifest), problems);
        else this.props.onLocal(problems);
        this.mark();
    }

    blockOf(problem) {
        const id = problem.blockId || blockForPath(this.where, problem.path || '');
        return id && this.ws ? this.ws.getBlockById(id) : null;
    }

    /** An outline on every block a problem points at (the controller's, then the blocks' own). */
    mark() {
        if (!this.ws) return;
        const now = new Set();
        for (const p of [...this.problems, ...this.local]) {
            const b = this.blockOf(p);
            if (b) now.add(b);
        }
        for (const b of this.marked) if (!now.has(b) && b.getSvgRoot()) b.getSvgRoot().classList.remove(PROBLEM_CLASS);
        for (const b of now) if (b.getSvgRoot()) b.getSvgRoot().classList.add(PROBLEM_CLASS);
        this.marked = now;
    }

    /** Scrolls to the block of a problem and gives it the keyboard focus. */
    show(problem) {
        const b = this.blockOf(problem);
        if (!b) return;
        this.ws.centerOnBlock(b.id);
        const B = window.Blockly;
        if (B.getFocusManager) B.getFocusManager().focusNode(b);
        else b.select();
    }

    render() {
        return html`<div class="scn-blocks" data-testid="scenario-blocks" role="region"
            aria-label=${t('scenario_blocks.workspace')} aria-describedby="scn-blocks-help"
            ref=${(el) => { this.host = el; }}></div>`;
    }
}
