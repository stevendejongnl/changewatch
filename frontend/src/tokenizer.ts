export type TokenType =
  | "keyword"
  | "string"
  | "comment"
  | "decorator"
  | "builtin"
  | "number"
  | "text";

export interface Token {
  type: TokenType;
  value: string;
}

const KEYWORDS = new Set([
  "and", "as", "assert", "async", "await", "break", "class", "continue",
  "def", "del", "elif", "else", "except", "False", "finally", "for",
  "from", "global", "if", "import", "in", "is", "lambda", "None",
  "nonlocal", "not", "or", "pass", "raise", "return", "True", "try",
  "while", "with", "yield",
]);

const BUILTINS = new Set([
  "abs", "all", "any", "bool", "bytes", "callable", "chr", "dict",
  "dir", "divmod", "enumerate", "eval", "exec", "filter", "float",
  "format", "frozenset", "getattr", "globals", "hasattr", "hash",
  "help", "hex", "id", "input", "int", "isinstance", "issubclass",
  "iter", "len", "list", "locals", "map", "max", "min", "next",
  "object", "oct", "open", "ord", "pow", "print", "property",
  "range", "repr", "reversed", "round", "set", "setattr", "slice",
  "sorted", "staticmethod", "str", "sum", "super", "tuple", "type",
  "vars", "zip",
]);

export function tokenize(code: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;

  while (i < code.length) {
    // Comment
    if (code[i] === "#") {
      const end = code.indexOf("\n", i);
      const value = end === -1 ? code.slice(i) : code.slice(i, end);
      tokens.push({ type: "comment", value });
      i += value.length;
      continue;
    }

    // Decorator
    if (code[i] === "@") {
      let end = i + 1;
      while (end < code.length && /[\w.]/.test(code[end])) end++;
      tokens.push({ type: "decorator", value: code.slice(i, end) });
      i = end;
      continue;
    }

    // Triple-quoted string (""" or ''')
    if (
      (code[i] === '"' && code.slice(i, i + 3) === '"""') ||
      (code[i] === "'" && code.slice(i, i + 3) === "'''")
    ) {
      const quote = code.slice(i, i + 3);
      const end = code.indexOf(quote, i + 3);
      if (end === -1) {
        tokens.push({ type: "string", value: code.slice(i) });
        i = code.length;
      } else {
        tokens.push({ type: "string", value: code.slice(i, end + 3) });
        i = end + 3;
      }
      continue;
    }

    // Single or double quoted string
    if (code[i] === '"' || code[i] === "'") {
      const quote = code[i];
      let end = i + 1;
      while (end < code.length && code[end] !== quote && code[end] !== "\n") {
        if (code[end] === "\\") end++; // skip escaped char
        end++;
      }
      if (end < code.length) end++; // include closing quote
      tokens.push({ type: "string", value: code.slice(i, end) });
      i = end;
      continue;
    }

    // Number
    if (/[0-9]/.test(code[i])) {
      let end = i;
      while (end < code.length && /[0-9._xXoObBa-fA-F]/.test(code[end])) end++;
      tokens.push({ type: "number", value: code.slice(i, end) });
      i = end;
      continue;
    }

    // Identifier (keyword, builtin, or text)
    if (/[a-zA-Z_]/.test(code[i])) {
      let end = i;
      while (end < code.length && /[a-zA-Z0-9_]/.test(code[end])) end++;
      const word = code.slice(i, end);
      if (KEYWORDS.has(word)) {
        tokens.push({ type: "keyword", value: word });
      } else if (BUILTINS.has(word)) {
        tokens.push({ type: "builtin", value: word });
      } else {
        tokens.push({ type: "text", value: word });
      }
      i = end;
      continue;
    }

    // Everything else (operators, whitespace, punctuation)
    tokens.push({ type: "text", value: code[i] });
    i++;
  }

  return tokens;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const TOKEN_CLASS: Record<TokenType, string | null> = {
  keyword: "t-acc",
  string: "t-ok",
  comment: "t-3",
  decorator: "t-3",
  builtin: "t-chg",
  number: "t-pen",
  text: null,
};

export function renderHighlighted(code: string): string {
  return tokenize(code)
    .map((tok) => {
      const cls = TOKEN_CLASS[tok.type];
      const escaped = escapeHtml(tok.value);
      return cls ? `<span class="${cls}">${escaped}</span>` : escaped;
    })
    .join("");
}
