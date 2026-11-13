#pragma once
// Reads the small JSON control messages of the server without a JSON library:
//   {"type":"ready"}  {"type":"phase","phase":"thinking|replying|searching"}
//   {"type":"disconnect",...}  {"type":"error","code":"insufficient_quota"}
// Anything else (unknown type, broken text) gives Kind::Unknown and is ignored by the caller.
#include <cstddef>
#include <string>

#include "state_machine.h"

namespace leyla {

enum class Kind { Unknown, Ready, Phase, Disconnect, QuotaError, OtherError };

struct Message {
  Kind kind = Kind::Unknown;
  Phase phase = Phase::Thinking;  // only valid for Kind::Phase
};

// Value of a string field: "key" ws : ws "value". Empty when not found.
inline std::string json_string(const std::string &text, const std::string &key) {
  std::string pat = "\"" + key + "\"";
  size_t p = text.find(pat);
  while (p != std::string::npos) {
    size_t i = p + pat.size();
    while (i < text.size() && (text[i] == ' ' || text[i] == '\t')) i++;
    if (i < text.size() && text[i] == ':') {
      i++;
      while (i < text.size() && (text[i] == ' ' || text[i] == '\t')) i++;
      if (i < text.size() && text[i] == '"') {
        size_t end = text.find('"', i + 1);
        if (end != std::string::npos) return text.substr(i + 1, end - i - 1);
      }
      return "";
    }
    p = text.find(pat, p + 1);
  }
  return "";
}

inline Message parse_message(const char *data, size_t len) {
  Message m;
  std::string text(data, len);
  std::string type = json_string(text, "type");
  if (type == "ready") {
    m.kind = Kind::Ready;
  } else if (type == "disconnect") {
    m.kind = Kind::Disconnect;
  } else if (type == "phase") {
    std::string ph = json_string(text, "phase");
    if (ph == "thinking") { m.kind = Kind::Phase; m.phase = Phase::Thinking; }
    else if (ph == "replying") { m.kind = Kind::Phase; m.phase = Phase::Replying; }
    else if (ph == "searching") { m.kind = Kind::Phase; m.phase = Phase::Searching; }
  } else if (type == "error") {
    m.kind = json_string(text, "code") == "insufficient_quota" ? Kind::QuotaError : Kind::OtherError;
  }
  return m;
}

}  // namespace leyla
