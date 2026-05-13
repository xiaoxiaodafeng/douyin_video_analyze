const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");

function cliOption(name, fallback) {
  const prefix = `--${name}=`;
  const hit = process.argv.find((arg) => arg.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : fallback;
}

function cliFlag(name) {
  return process.argv.includes(`--${name}`);
}

function usage() {
  console.log("Usage:");
  console.log("  node scripts/comment_crawl_runner.js VIDEO_ID --limit=200 --reply-limit=50 --output=outputs/file.json");
}

function emit(event) {
  process.stdout.write(`${JSON.stringify(event)}\n`);
}

function parseValue(line, prefix) {
  if (!line.startsWith(prefix)) return null;
  return line.slice(prefix.length).trim();
}

async function main() {
  const videoId = process.argv.slice(2).find((arg) => !arg.startsWith("--"));
  if (!videoId || cliFlag("help") || cliFlag("h")) {
    usage();
    process.exit(0);
  }

  const repoRoot = path.resolve(__dirname, "..");
  const analyzeRoot = process.env.DY_ANALYZE_PATH || "E:\\dy_analyze";
  const crawlerScript = path.join(analyzeRoot, "douyin_crawler_server.js");
  const output = cliOption("output", path.join(repoRoot, "outputs", `douyin_comments_${videoId}_bridge.json`));
  const limit = Number(cliOption("limit", "200"));
  const replyLimit = Number(cliOption("reply-limit", "50"));

  if (!fs.existsSync(crawlerScript)) {
    throw new Error(`crawler script not found: ${crawlerScript}`);
  }

  const outAbs = path.resolve(output);
  fs.mkdirSync(path.dirname(outAbs), { recursive: true });

  emit({
    type: "progress",
    stage: "validate",
    status: "running",
    video_id: videoId,
    top_count: 0,
    reply_count: 0,
    comments_synced: 0,
    message: "开始校验视频与抓取参数",
  });

  const child = spawn(
    "node",
    [
      crawlerScript,
      String(videoId),
      `--limit=${limit}`,
      `--reply-limit=${replyLimit}`,
      `--output=${outAbs}`,
    ],
    {
      cwd: analyzeRoot,
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  let stdoutBuf = "";
  let stderrBuf = "";
  let topCount = 0;
  let replyCount = 0;
  let topTotal = limit;
  let validated = false;

  const handleLine = (line) => {
    const text = String(line || "").trim();
    if (!text) return;

    const video = parseValue(text, "video_id=");
    if (video) {
      validated = true;
      emit({
        type: "progress",
        stage: "validate",
        status: "done",
        video_id: video,
        top_count: 0,
        reply_count: 0,
        comments_synced: 0,
        message: `视频校验通过：${video}`,
      });
      return;
    }

    const limitText = parseValue(text, "limit=");
    if (limitText) {
      topTotal = Number(limitText) || topTotal;
      emit({
        type: "progress",
        stage: "top",
        status: "running",
        video_id: videoId,
        top_count: topCount,
        top_target: topTotal,
        reply_count: replyCount,
        comments_synced: topCount + replyCount,
        message: `准备抓取一级评论，目标 ${topTotal} 条`,
      });
      return;
    }

    const topCommentsText = parseValue(text, "top_comments=");
    if (topCommentsText) {
      topCount = Number(topCommentsText) || topCount;
      emit({
        type: "progress",
        stage: "top",
        status: "done",
        video_id: videoId,
        top_count: topCount,
        top_target: topTotal,
        reply_count: replyCount,
        comments_synced: topCount + replyCount,
        message: `已抓一级评论 ${topCount} 条`,
      });
      return;
    }

    const repliesCollectedText = parseValue(text, "replies_collected=");
    if (repliesCollectedText) {
      replyCount = Number(repliesCollectedText) || replyCount;
      emit({
        type: "progress",
        stage: "reply",
        status: "done",
        video_id: videoId,
        top_count: topCount,
        top_target: topTotal,
        reply_count: replyCount,
        comments_synced: topCount + replyCount,
        message: `已抓一级评论 ${topCount} 条 / 二级评论 ${replyCount} 条`,
      });
      emit({
        type: "progress",
        stage: "save",
        status: "running",
        video_id: videoId,
        top_count: topCount,
        top_target: topTotal,
        reply_count: replyCount,
        comments_synced: topCount + replyCount,
        message: "抓取完成，等待系统入库",
      });
      return;
    }

    if (text.startsWith("reply ")) {
      const match = text.match(/reply\s+(\d+)\/(\d+):.*replies=(\d+)/);
      if (match) {
        const current = Number(match[1] || 0);
        const total = Number(match[2] || 0);
        const currentReplies = Number(match[3] || 0);
        replyCount += currentReplies;
        topCount = Math.max(topCount, total);
        emit({
          type: "progress",
          stage: "reply",
          status: "running",
          video_id: videoId,
          top_count: topCount,
          top_target: topTotal,
          reply_count: replyCount,
          reply_done: current,
          reply_total: total,
          comments_synced: topCount + replyCount,
          message: `已抓一级评论 ${topCount} 条 / 二级评论 ${replyCount} 条`,
        });
      }
      return;
    }

    emit({
      type: "log",
      stage: validated ? "crawl" : "validate",
      message: text,
    });
  };

  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    stdoutBuf += chunk;
    const lines = stdoutBuf.split(/\r?\n/);
    stdoutBuf = lines.pop() || "";
    for (const line of lines) handleLine(line);
  });

  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => {
    stderrBuf += chunk;
    const lines = String(chunk).split(/\r?\n/).filter(Boolean);
    for (const line of lines) {
      emit({
        type: "log",
        stage: "stderr",
        message: line,
      });
    }
  });

  const exitCode = await new Promise((resolve) => child.on("close", resolve));
  if (stdoutBuf.trim()) handleLine(stdoutBuf.trim());

  if (exitCode !== 0) {
    throw new Error(stderrBuf.trim() || `crawler exited with code ${exitCode}`);
  }

  emit({
    type: "done",
    stage: "save",
    status: "done",
    video_id: videoId,
    top_count: topCount,
    top_target: topTotal,
    reply_count: replyCount,
    comments_synced: topCount + replyCount,
    output: outAbs,
    message: `抓取完成：一级评论 ${topCount} 条，二级评论 ${replyCount} 条`,
  });
}

main().catch((error) => {
  emit({
    type: "error",
    stage: "crawl",
    status: "failed",
    message: error && error.message ? error.message : String(error),
  });
  process.exit(1);
});
