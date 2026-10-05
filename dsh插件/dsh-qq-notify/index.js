/**
 * dsh-email-notify — 任务完成后「通知主人」。已改造：不再发邮件，改为通过 AstrBot(bot) 直接发 QQ 消息。
 *
 * Host half. Registers the `notify_owner` tool (the agent calls it) and mounts a
 * system-prompt section that nudges the model to notify the owner via QQ when a
 * task finishes. The AstrBot endpoint / im api key / target umo are read from
 * `~/.dsh/dsh-qq-notify.json` at call time so the key never lives in source,
 * in tool arguments, or in the chat transcript.
 *
 * Delivery: POST http://127.0.0.1:6185/api/v1/im/messages
 *   header: Authorization: Bearer <im_api_key>   (im scope)
 *   body  : { "umo": "onebot-qq:GroupMessage:<TEST_GROUP_ID>",
 *             "message": [{ "type": "plain", "text": "..." }] }
 *   umo 由 ~/.dsh/dsh-qq-notify.json 决定（当前=群 <TEST_GROUP_ID>）。
 */
import { defineTool } from '@deepseek-ai/dsh-tools';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export const name = 'dsh-email-notify';
export const inject = ['tools', 'systemPrompt'];

const CONFIG_PATH = path.join(os.homedir(), '.dsh', 'dsh-qq-notify.json');

function loadConfig() {
    try {
        if (!fs.existsSync(CONFIG_PATH)) {
            return null;
        }
        const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
        return {
            astrbotUrl: (cfg.astrbot_url ?? 'http://127.0.0.1:6185').replace(/\/+$/, ''),
            imApiKey: cfg.im_api_key,
            umo: cfg.umo ?? 'onebot-qq:GroupMessage:<TEST_GROUP_ID>',
        };
    }
    catch {
        return null;
    }
}

function renderNotify(_args, value) {
    return [{ type: 'text', text: value.message }];
}

export function apply(ctx) {
    ctx.tools.register(defineTool({
        name: 'notify_owner',
        description: 'Send a QQ message to the owner through AstrBot so they get notified when a task finishes. ' +
            'Call this AFTER finishing a task, with a concise summary of the outcome and key results. ' +
            'Do not call it on every intermediate step.',
        parameters: {
            message: {
                type: 'string',
                required: true,
                description: '要发给主人的消息内容：简洁写明任务结论与关键结果（可直接发到 QQ 的纯文本）。',
            },
        },
        output: {
            schema: { type: 'object', additionalProperties: true },
            render: renderNotify,
        },
        execute: async (args) => {
            const cfg = loadConfig();
            if (!cfg || !cfg.imApiKey) {
                throw new Error(`QQ 通知配置缺失：请在 ${CONFIG_PATH} 写入 {"astrbot_url","im_api_key","umo"}。`);
            }
            const url = cfg.astrbotUrl + '/api/v1/im/messages';
            const body = JSON.stringify({
                umo: cfg.umo,
                message: [{ type: 'plain', text: args.message }],
            });
            const resp = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + cfg.imApiKey,
                },
                body,
            });
            const text = await resp.text().catch(() => '');
            if (!resp.ok) {
                throw new Error(`AstrBot 发送失败 HTTP ${resp.status}: ${text.slice(0, 300)}`);
            }
            const head = args.message.length > 60 ? args.message.slice(0, 60) + '…' : args.message;
            return { ok: true, message: `已通过 QQ 通知主人（${cfg.umo}）：${head}` };
        },
        timeoutMs: 20000,
    }));

    // System-prompt nudge: notify the owner via QQ the moment a task wraps up.
    try {
        ctx.effect(() => {
            return ctx.systemPrompt.section({
                name: 'dsh-qq-notify',
                order: 20,
                text: '任务完成后通知主人：当一次任务执行完毕、向用户给出最终结论时，调用 notify_owner 工具，' +
                    '把任务结果摘要通过 AstrBot 发到主人的 QQ 群（具体目标由 ~/.dsh/dsh-qq-notify.json 的 umo 指定，当前是群 <TEST_GROUP_ID>；' +
                    '不要自己拼 umo、也不要试图改成私聊）。' +
                    '消息用一句话概括本次任务，并写明任务结论与关键结果。' +
                    '仅在任务确实完成时发送，不要在中间步骤重复发送。',
            });
        }, 'dsh-qq-notify: section sync');
    }
    catch {
        // systemPrompt not available in this environment — tool still works.
    }
}
