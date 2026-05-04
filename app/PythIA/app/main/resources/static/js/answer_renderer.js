(function () {
  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderInline(value) {
    const codeSpans = [];
    const withCodeTokens = String(value ?? "").replace(/`([^`]+)`/g, function (_, code) {
      const token = `%%CODESPAN${codeSpans.length}%%`;
      codeSpans.push(`<code>${escapeHtml(code)}</code>`);
      return token;
    });

    let html = escapeHtml(withCodeTokens);
    html = html
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_]+)__/g, "<strong>$1</strong>")
      .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
      .replace(/_([^_\n]+)_/g, "<em>$1</em>");

    codeSpans.forEach(function (codeHtml, index) {
      html = html.replace(`%%CODESPAN${index}%%`, codeHtml);
    });

    return html;
  }

  function isTableSeparator(line) {
    return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  }

  function isTableStart(lines, index) {
    return lines[index]?.includes("|") && isTableSeparator(lines[index + 1] || "");
  }

  function splitTableRow(line) {
    return line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map(function (cell) {
        return cell.trim();
      });
  }

  function renderTable(lines, startIndex) {
    const headers = splitTableRow(lines[startIndex]);
    const bodyRows = [];
    let index = startIndex + 2;

    while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
      bodyRows.push(splitTableRow(lines[index]));
      index += 1;
    }

    const headerHtml = headers
      .map(function (header) {
        return `<th>${renderInline(header)}</th>`;
      })
      .join("");

    const bodyHtml = bodyRows
      .map(function (row) {
        const cellsHtml = row
          .map(function (cell) {
            return `<td>${renderInline(cell)}</td>`;
          })
          .join("");
        return `<tr>${cellsHtml}</tr>`;
      })
      .join("");

    return {
      html: `<div class="rag-table-wrap"><table><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`,
      nextIndex: index,
    };
  }

  function renderMarkdown(markdown) {
    const lines = String(markdown ?? "").replace(/\r\n?/g, "\n").split("\n");
    const blocks = [];
    let index = 0;

    while (index < lines.length) {
      const line = lines[index];

      if (!line.trim()) {
        index += 1;
        continue;
      }

      const fence = line.match(/^\s*```([\w-]*)\s*$/);
      if (fence) {
        const codeLines = [];
        index += 1;
        while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
          codeLines.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        blocks.push(`<pre class="rag-code-block"><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        continue;
      }

      if (isTableStart(lines, index)) {
        const table = renderTable(lines, index);
        blocks.push(table.html);
        index = table.nextIndex;
        continue;
      }

      const heading = line.match(/^(#{1,4})\s+(.+)$/);
      if (heading) {
        const level = Math.min(heading[1].length + 2, 6);
        blocks.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
        index += 1;
        continue;
      }

      if (/^\s*>\s?/.test(line)) {
        const quoteLines = [];
        while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
          quoteLines.push(lines[index].replace(/^\s*>\s?/, ""));
          index += 1;
        }
        blocks.push(`<blockquote>${quoteLines.map(renderInline).join("<br>")}</blockquote>`);
        continue;
      }

      const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
      if (unordered) {
        const items = [];
        while (index < lines.length) {
          const item = lines[index].match(/^\s*[-*+]\s+(.+)$/);
          if (!item) break;
          items.push(`<li>${renderInline(item[1])}</li>`);
          index += 1;
        }
        blocks.push(`<ul>${items.join("")}</ul>`);
        continue;
      }

      const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
      if (ordered) {
        const items = [];
        while (index < lines.length) {
          const item = lines[index].match(/^\s*\d+[.)]\s+(.+)$/);
          if (!item) break;
          items.push(`<li>${renderInline(item[1])}</li>`);
          index += 1;
        }
        blocks.push(`<ol>${items.join("")}</ol>`);
        continue;
      }

      const paragraphLines = [line.trim()];
      index += 1;
      while (
        index < lines.length &&
        lines[index].trim() &&
        !/^\s*```/.test(lines[index]) &&
        !/^(#{1,4})\s+/.test(lines[index]) &&
        !/^\s*>\s?/.test(lines[index]) &&
        !/^\s*[-*+]\s+/.test(lines[index]) &&
        !/^\s*\d+[.)]\s+/.test(lines[index]) &&
        !isTableStart(lines, index)
      ) {
        paragraphLines.push(lines[index].trim());
        index += 1;
      }
      blocks.push(`<p>${paragraphLines.map(renderInline).join("<br>")}</p>`);
    }

    return blocks.join("");
  }

  window.pythiaRenderMarkdown = function (target, markdown) {
    if (!target) return;
    target.innerHTML = renderMarkdown(markdown);
  };
})();
