/**
 * GoRules Lite — Frontend Alpine.js controller logic
 */

document.addEventListener('alpine:init', () => {
    Alpine.data('tableEditor', () => ({
        currentTab: 'editor',
        funcName: '',
        functions: [],
        isRenaming: false,
        renameValue: '',
        isCreating: false,
        newTableName: '',
        isEvaluating: false,
        evalData: null,
        evalStatus: '',
        testerOpen: true,
        versionsOpen: true,
        hintsOpen: true,
        inputSchema: [],
        outputsSchema: [],
        triggers: [],
        newTrigger: { path: '', function_name: '', description: '' },
        isRouting: false,
        routeResult: null,
        routeStatus: '',
        testRoutePath: 'discount',
        testRouteContext: JSON.stringify({ customer_tier: 'vip', cart_total: 1200 }, null, 2),
        testInput: '',

        init() {
            const root = document.getElementById('app-root');
            if (root) {
                this.funcName = root.dataset.selectedFunc || '';
                try {
                    this.functions = JSON.parse(root.dataset.functions || '[]');
                } catch (e) {
                    console.error('Failed to parse functions from data attribute:', e);
                }
            }

            if (this.funcName) {
                this.loadTable(this.funcName);
            }
            this.loadTriggers();

            // Persist testInput per-function in localStorage
            this.$watch('testInput', val => {
                if (this.funcName) {
                    localStorage.setItem('dt_input_' + this.funcName, val);
                }
            });
        },

        async reloadFunctions() {
            try {
                const r = await fetch('/api/functions');
                if (r.ok) {
                    this.functions = await r.json();
                }
            } catch (e) {
                console.error(e);
            }
        },

        async createTable() {
            const name = this.newTableName.trim();
            if (!name) return;
            const r = await fetch('/api/table', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'name=' + encodeURIComponent(name)
            });
            if (r.ok) {
                this.isCreating = false;
                this.newTableName = '';
                await this.reloadFunctions();
                this.funcName = name;
                await this.loadTable(name);
            } else {
                const d = await r.json();
                alert('Error: ' + (d.detail || 'Could not create'));
            }
        },

        async renameTable() {
            const newName = this.renameValue.trim();
            if (!newName) return;
            if (newName === this.funcName) {
                this.isRenaming = false;
                return;
            }
            const r = await fetch('/api/table/' + this.funcName + '/rename', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'new_name=' + encodeURIComponent(newName)
            });
            if (r.ok) {
                const d = await r.json();
                // Migrate localStorage key
                const stored = localStorage.getItem('dt_input_' + this.funcName);
                if (stored) {
                    localStorage.setItem('dt_input_' + d.name, stored);
                    localStorage.removeItem('dt_input_' + this.funcName);
                }
                this.funcName = d.name;
                this.isRenaming = false;
                await this.reloadFunctions();
                await this.loadTable(d.name);
            } else {
                const d = await r.json();
                alert('Error: ' + (d.detail || 'Could not rename'));
            }
        },

        async loadTable(name) {
            if (!name) return;
            this.evalData = null;
            this.evalStatus = '';
            this.inputSchema = [];
            this.outputsSchema = [];
            
            // Fetch layout via HTMX swap
            htmx.ajax('GET', '/api/table/' + name, { target: '#editor-container', swap: 'innerHTML' });
            
            // Load schema for tester hints
            try {
                const r = await fetch('/api/table/' + name + '/schema');
                if (r.ok) {
                    const s = await r.json();
                    this.inputSchema = s.inputs || [];
                    this.outputsSchema = s.outputs || [];
                    // Restore from localStorage, or build sample from schema
                    const stored = localStorage.getItem('dt_input_' + name);
                    if (stored) {
                        this.testInput = stored;
                    } else {
                        const sample = {};
                        for (const col of (s.inputs || [])) {
                            sample[col.name] = col.type === 'number' ? 0 : col.type === 'boolean' ? false : '';
                        }
                        this.testInput = JSON.stringify(sample, null, 2);
                    }
                }
            } catch (e) {
                console.error(e);
            }
        },

        async evaluateRules() {
            if (!this.funcName) return;
            this.isEvaluating = true;
            this.evalStatus = 'running';
            this.evalData = null;
            try {
                let body = {};
                try {
                    body = JSON.parse(this.testInput || '{}');
                } catch (e) {
                    throw new Error('Invalid JSON: ' + e.message);
                }
                const r = await fetch('/evaluate/' + this.funcName, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                const data = await r.json();
                if (!r.ok) {
                    this.evalStatus = 'error';
                    this.evalData = { error: data.detail || 'Server error' };
                    return;
                }
                this.evalStatus = data.matched ? 'matched' : 'no-match';
                this.evalData = data;
                // Refresh schema from response
                if (data.outputs_schema) {
                    this.outputsSchema = data.outputs_schema;
                }
            } catch (e) {
                this.evalStatus = 'error';
                this.evalData = { error: e.message };
            } finally {
                this.isEvaluating = false;
            }
        },

        async loadTriggers() {
            try {
                const r = await fetch('/api/triggers');
                if (r.ok) {
                    this.triggers = await r.json();
                }
            } catch (e) {
                console.error(e);
            }
        },

        async createTrigger() {
            try {
                const r = await fetch('/api/triggers', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.newTrigger)
                });
                if (r.ok) {
                    this.newTrigger = { path: '', function_name: '', description: '' };
                    await this.loadTriggers();
                } else {
                    const d = await r.json();
                    alert('Error: ' + (d.detail || 'Could not create'));
                }
            } catch (e) {
                alert(e.message);
            }
        },

        async deleteTrigger(path) {
            if (!confirm('Delete /route/' + path + '?')) return;
            await fetch('/api/triggers/' + path, { method: 'DELETE' });
            await this.loadTriggers();
        },

        async testRoute() {
            if (!this.testRoutePath.trim()) return;
            this.isRouting = true;
            this.routeStatus = 'running';
            this.routeResult = null;
            try {
                let body = {};
                try {
                    body = JSON.parse(this.testRouteContext || '{}');
                } catch (e) {
                    throw new Error('Invalid JSON: ' + e.message);
                }
                const r = await fetch('/route/' + this.testRoutePath.trim(), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                const data = await r.json();
                this.routeStatus = r.ok ? 'ok' : 'error';
                this.routeResult = JSON.stringify(data, null, 2);
            } catch (e) {
                this.routeStatus = 'error';
                this.routeResult = e.message;
            } finally {
                this.isRouting = false;
            }
        },

        typeIcon(t) {
            return t === 'number' ? '🔢' : t === 'boolean' ? '⊨' : '🔤';
        }
    }));
});

// Compile dynamic HTML elements swapped by HTMX so Alpine.js can process their directives
document.addEventListener('htmx:afterSwap', (event) => {
    if (typeof Alpine !== 'undefined' && event.detail.target) {
        Alpine.process(event.detail.target);
    }
});
