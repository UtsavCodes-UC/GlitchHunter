export function Busy({ text }: { text: string }) {
  return <span className="busy"><span className="spin" />{text}</span>;
}

export function ErrorBox({ message }: { message: string | null }) {
  return message ? <div className="error">{message}</div> : null;
}
