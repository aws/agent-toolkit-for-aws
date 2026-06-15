#!/usr/bin/env node
/**
 * generate-pdf.ts — Node.js entry point for PDF generation.
 *
 * Reads one or more pricing-estimate JSON documents (output of
 * `calculate.ts` / `parse-cassandra.ts`) and writes a PDF report to disk.
 *
 * Single estimate:
 *     # via stdin (backwards-compat)
 *     npx ts-node ... scripts/parse-cassandra.ts ... \
 *       | npx ts-node ... scripts/generate-pdf.ts
 *
 *     # via flag
 *     npx ts-node ... scripts/generate-pdf.ts --input /tmp/keyspaces-calc.json
 *
 * Multiple estimates (consolidated into a single comparison report):
 *     npx ts-node ... scripts/generate-pdf.ts \
 *         --input /tmp/optA.json --label "Option A" \
 *         --input /tmp/optB.json --label "Option B" \
 *         --input /tmp/optC.json --label "Option C" \
 *         --output /tmp/comparison.pdf
 *
 * All flags:
 *   --input <path>    Path to a calculate.ts / parse-cassandra.ts JSON file. Repeatable.
 *   --label <name>    Display label for the most recent --input. Optional.
 *   --output <path>   PDF output path (default: ./keyspaces-pricing-estimate.pdf).
 *   -h | --help       Show usage.
 *
 * Delegates all PDF rendering to src/calculator/CreatePDFReport.ts.
 */

import fs from 'fs';
import path from 'path';
import CreatePDFReport, {
    type CompatibilityData,
    type Estimate,
} from './calculator/CreatePDFReport';

// ---------------------------------------------------------------------------
// Subclass that writes the finished PDF to the filesystem instead of
// triggering a browser download.
// ---------------------------------------------------------------------------

class NodePDFReport extends CreatePDFReport {
    private readonly filePath: string;

    constructor(filePath: string) {
        super();
        this.filePath = filePath;
    }

    protected _output(): void {
        const buffer = new Uint8Array(this.doc.output('arraybuffer') as ArrayBuffer);
        fs.writeFileSync(this.filePath, buffer);
        console.error(`PDF saved: ${this.filePath}`);
    }
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

interface CliInput {
    path: string;
    label: string | null;
}

interface CliArgs {
    inputs: CliInput[];
    output: string | null;
}

function printHelp(): void {
    console.error(`Usage:
  generate-pdf.ts                                              # read single JSON from stdin
  generate-pdf.ts --input <path> [--label <name>]              # single estimate from a file
  generate-pdf.ts --input <a.json> [--label A] \\
                  --input <b.json> [--label B] ...             # multi-estimate consolidated report
  generate-pdf.ts ... --output <path.pdf>                      # custom output path
                                                                 (default: ./keyspaces-pricing-estimate.pdf)
`);
}

function parseCli(argv: string[]): CliArgs {
    const args: CliArgs = { inputs: [], output: null };
    let i = 0;
    while (i < argv.length) {
        const a = argv[i];
        switch (a) {
            case '--input': {
                const p = argv[++i];
                if (!p) throw new Error('--input requires a path argument');
                args.inputs.push({ path: p, label: null });
                break;
            }
            case '--label': {
                const l = argv[++i];
                if (!l) throw new Error('--label requires a name argument');
                if (args.inputs.length === 0) {
                    throw new Error('--label must follow a --input flag');
                }
                args.inputs[args.inputs.length - 1].label = l;
                break;
            }
            case '--output':
            case '-o': {
                const o = argv[++i];
                if (!o) throw new Error('--output requires a path argument');
                args.output = o;
                break;
            }
            case '-h':
            case '--help':
                printHelp();
                process.exit(0);
                break;
            default:
                throw new Error(`Unknown argument: ${a}`);
        }
        i++;
    }
    return args;
}

// ---------------------------------------------------------------------------
// JSON helpers
// ---------------------------------------------------------------------------

interface ReportDataShape {
    datacenters: Estimate['datacenters'];
    regions: Estimate['regions'];
    estimateResults: Estimate['estimateResults'];
    pricing: Estimate['pricing'];
}

interface RawCompatibility {
    has_issues?: boolean;
    details?: {
        schema?: {
            functions?: number;
            aggregates?: number;
            keyspaces?: Record<string, Record<string, {
                indexes: string[];
                triggers: string[];
                materializedViews: string[];
            }>>;
        } | null;
        query_patterns?: {
            lwt_in_unlogged_batch?: Array<{ prepared_id?: string; query_string: string }>;
            aggregations?: Array<{ prepared_id?: string; function?: string; query_string: string }>;
        } | null;
    };
}

function readJsonFileSync(p: string): Record<string, unknown> {
    const raw = fs.readFileSync(p, 'utf8');
    try {
        return JSON.parse(raw);
    } catch (e: unknown) {
        throw new Error('Failed to parse JSON file: invalid JSON content');
    }
}

function readJsonStdinSync(): Record<string, unknown> {
    const raw = fs.readFileSync(0, 'utf8');
    if (!raw.trim()) {
        throw new Error('No JSON received on stdin');
    }
    try {
        return JSON.parse(raw);
    } catch (e: unknown) {
        throw new Error('Failed to parse JSON from stdin: invalid JSON content');
    }
}

function extractEstimate(json: Record<string, unknown>, label: string): Estimate {
    const reportData = json.report_data as ReportDataShape | undefined;
    if (!reportData) {
        throw new Error(`Input JSON for "${label}" is missing report_data — was it produced by calculate.ts or parse-cassandra.ts?`);
    }
    const compat = json.compatibility as RawCompatibility | undefined;
    return {
        label,
        datacenters: reportData.datacenters,
        regions: reportData.regions,
        estimateResults: reportData.estimateResults,
        pricing: reportData.pricing,
        tcoData: null,
        compatibilityData: compatToReport(compat ?? null),
    };
}

function compatToReport(compat: RawCompatibility | null): CompatibilityData | null {
    if (!compat) return null;
    const schema = compat.details?.schema ?? null;
    const qp = compat.details?.query_patterns ?? null;
    if (!schema && !qp) return null;
    return {
        functions: schema?.functions ?? 0,
        aggregates: schema?.aggregates ?? 0,
        keyspaces: schema?.keyspaces ?? {},
        queryPatterns: qp ? {
            lwtInUnloggedBatch: (qp.lwt_in_unlogged_batch ?? []).map(item => ({
                prepared_id: item.prepared_id,
                query_string: item.query_string,
            })),
            aggregations: (qp.aggregations ?? []).map(item => ({
                prepared_id: item.prepared_id,
                query_string: item.query_string,
            })),
        } : undefined,
    };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function resolveOutputPath(output: string | null): string {
    if (!output) return path.join(process.cwd(), 'keyspaces-pricing-estimate.pdf');
    return path.isAbsolute(output) ? output : path.join(process.cwd(), output);
}

function main(): void {
    let cli: CliArgs;
    try {
        cli = parseCli(process.argv.slice(2));
    } catch (e: unknown) {
        console.error((e as Error).message);
        printHelp();
        process.exit(1);
        return;
    }

    const outputPath = resolveOutputPath(cli.output);
    const estimates: Estimate[] = [];

    if (cli.inputs.length === 0) {
        if (process.stdin.isTTY) {
            console.error('No --input flags and stdin is a TTY. Provide JSON via stdin or --input.');
            printHelp();
            process.exit(1);
        }
        try {
            const json = readJsonStdinSync();
            estimates.push(extractEstimate(json, 'Estimate'));
        } catch (e: unknown) {
            console.error((e as Error).message);
            process.exit(1);
        }
    } else {
        for (const [idx, inp] of cli.inputs.entries()) {
            try {
                const json = readJsonFileSync(inp.path);
                const label = inp.label ?? `Estimate ${idx + 1}`;
                estimates.push(extractEstimate(json, label));
            } catch (e: unknown) {
                console.error((e as Error).message);
                process.exit(1);
            }
        }
    }

    const report = new NodePDFReport(outputPath);

    if (estimates.length === 1) {
        const e = estimates[0];
        report.createReport(
            e.datacenters,
            e.regions,
            e.estimateResults,
            e.pricing,
            e.tcoData ?? null,
            e.compatibilityData ?? null,
        );
    } else {
        report.createMultiReport(estimates);
    }
}

main();
