import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs'

// Expose Mermaid for Material for MkDocs.
mermaid.initialize({
    startOnLoad: false,
})

window.mermaid = mermaid

function normalizeMermaidBlocks() {
    document.querySelectorAll('pre.mermaid').forEach((diagram) => {
        if (diagram.dataset.mermaidNormalized === 'true') {
            return
        }

        const codeBlock = diagram.querySelector('code')
        if (codeBlock) {
            // MkDocs wraps fenced Mermaid blocks in <pre><code>. Mermaid 11
            // expects the diagram source as the direct text content of the
            // .mermaid element, so unwrap it before rendering.
            diagram.textContent = codeBlock.textContent
        }

        diagram.dataset.mermaidNormalized = 'true'
    })
}

function renderMermaid() {
    normalizeMermaidBlocks()

    const diagrams = document.querySelectorAll('pre.mermaid:not([data-processed])')
    if (!diagrams.length) {
        return
    }

    mermaid.run({
        querySelector: 'pre.mermaid:not([data-processed])',
    })
}

function startMermaidRendering() {
    // Render on a direct page load, even if this module is evaluated after
    // DOMContentLoaded has already fired.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            renderMermaid()
        }, { once: true })
    } else {
        renderMermaid()
    }

    // Material for MkDocs uses instant navigation, so Mermaid also needs to
    // re-run after each document$ page swap.
    if (window.document$?.subscribe) {
        window.document$.subscribe(() => {
            renderMermaid()
        })
    }
}

startMermaidRendering()
