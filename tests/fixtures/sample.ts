// tests/fixtures/sample.ts
export function greet(name: string): string {
  return `Hello, ${name}`;
}

export class AuthService {
  login(userId: number, password: string): boolean {
    return password === "secret";
  }

  logout(userId: number): void {}
}

const helper = () => "helper";
