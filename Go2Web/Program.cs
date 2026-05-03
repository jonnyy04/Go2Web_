using System;
using System.IO;
using System.Net.Security;
using System.Net.Sockets;
using System.Text;
using System.Collections.Generic;

public class SimpleHttp
{
    public static string MakeRequest(string url)
    {
        Uri uri = new Uri(url);
        string host = uri.Host;
        int port = uri.Port != -1 ? uri.Port : (uri.Scheme == "https" ? 443 : 80);
        string path = uri.PathAndQuery;

        // 1. Deschidem conexiunea TCP
        using (TcpClient client = new TcpClient(host, port))
        using (Stream networkStream = client.GetStream())
        {
            Stream finalStream = networkStream;

            // 2. Dacă este HTTPS, aplicăm stratul de SSL/TLS
            if (uri.Scheme == "https")
            {
                var sslStream = new SslStream(networkStream, false);
                sslStream.AuthenticateAsClient(host);
                finalStream = sslStream;
            }

            // 3. Construim manual cererea HTTP (exact ca în string-ul tău din Python)
            string request = $"GET {path} HTTP/1.1\r\n" +
                             $"Host: {host}\r\n" +
                             "Accept: text/html,application/json\r\n" +
                             "Connection: close\r\n" +
                             "User-Agent: go2web/1.0\r\n\r\n";

            byte[] requestBytes = Encoding.UTF8.GetBytes(request);
            finalStream.Write(requestBytes, 0, requestBytes.Length);

            // 4. Citim răspunsul brut într-un MemoryStream pentru a evita pierderile de date
            using (MemoryStream ms = new MemoryStream())
            {
                byte[] buffer = new byte[4096];
                int bytesRead;
                while ((bytesRead = finalStream.Read(buffer, 0, buffer.Length)) > 0)
                {
                    ms.Write(buffer, 0, bytesRead);
                }

                // Returnăm tot conținutul ca string (headers + body)
                return Encoding.UTF8.GetString(ms.ToArray());
            }
        }
    }

    public static void Main(string[] args)
    {
        try
        {
            if (args.Length == 0)
            {
                Console.WriteLine("Utilizare: dotnet run -- <URL>");
                Console.WriteLine("Exemplu: dotnet run -- https://example.com");
                return;
            }

            string url = args[0];
            Console.WriteLine($"Request la: {url}\n");
            string response = MakeRequest(url);

            Console.WriteLine("--- RASPUNS BRUT ---");
            Console.WriteLine(response);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Eroare: {ex.Message}");
        }
    }
}