import Foundation
import CryptoKit
import CommonCrypto

enum DataExporter {
    enum ExportError: LocalizedError {
        case serializationFailed
        case encryptionFailed
        case decryptionFailed
        case invalidFormat

        var errorDescription: String? {
            switch self {
            case .serializationFailed: return "Data serialization failed"
            case .encryptionFailed: return "Encryption failed"
            case .decryptionFailed: return "Decryption failed – wrong password?"
            case .invalidFormat: return "Invalid file format"
            }
        }
    }

    private static let saltLength = 16
    private static let iterations: UInt32 = 100_000

    /// Encrypt data dict with user password → Data ready to write to .htdata file
    static func export(data: [String: Any], password: String) throws -> Data {
        guard JSONSerialization.isValidJSONObject(data),
              let json = try? JSONSerialization.data(withJSONObject: data, options: [.sortedKeys]) else {
            throw ExportError.serializationFailed
        }

        let salt = randomBytes(count: saltLength)
        let key = try deriveKey(password: password, salt: salt)

        guard let sealedBox = try? AES.GCM.seal(json, using: key) else {
            throw ExportError.encryptionFailed
        }

        // File format: salt + nonce + ciphertext + tag
        var result = Data()
        result.append(salt)
        result.append(contentsOf: sealedBox.nonce)
        result.append(sealedBox.ciphertext)
        result.append(sealedBox.tag)
        return result
    }

    /// Decrypt .htdata file → data dict (for future import)
    static func decrypt(fileData: Data, password: String) throws -> [String: Any] {
        let nonceLength = 12
        let tagLength = 16
        let minLength = saltLength + nonceLength + tagLength
        guard fileData.count > minLength else { throw ExportError.invalidFormat }

        let salt = fileData.prefix(saltLength)
        let nonce = fileData[saltLength..<(saltLength + nonceLength)]
        let ciphertext = fileData[(saltLength + nonceLength)..<(fileData.count - tagLength)]
        let tag = fileData.suffix(tagLength)

        let key = try deriveKey(password: password, salt: salt)

        guard let aesNonce = try? AES.GCM.Nonce(data: nonce),
              let sealedBox = try? AES.GCM.SealedBox(nonce: aesNonce, ciphertext: ciphertext, tag: tag),
              let plaintext = try? AES.GCM.open(sealedBox, using: key) else {
            throw ExportError.decryptionFailed
        }

        guard let json = try? JSONSerialization.jsonObject(with: plaintext) as? [String: Any] else {
            throw ExportError.invalidFormat
        }
        return json
    }

    // MARK: - Private

    private static func deriveKey(password: String, salt: Data) throws -> SymmetricKey {
        let passwordData = Data(password.utf8)
        var derivedKey = Data(count: 32) // 256-bit
        let status = derivedKey.withUnsafeMutableBytes { derivedKeyBytes in
            salt.withUnsafeBytes { saltBytes in
                passwordData.withUnsafeBytes { passwordBytes in
                    CCKeyDerivationPBKDF(
                        CCPBKDFAlgorithm(kCCPBKDF2),
                        passwordBytes.baseAddress?.assumingMemoryBound(to: Int8.self),
                        passwordData.count,
                        saltBytes.baseAddress?.assumingMemoryBound(to: UInt8.self),
                        salt.count,
                        CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256),
                        iterations,
                        derivedKeyBytes.baseAddress?.assumingMemoryBound(to: UInt8.self),
                        32
                    )
                }
            }
        }
        guard status == kCCSuccess else { throw ExportError.encryptionFailed }
        return SymmetricKey(data: derivedKey)
    }

    private static func randomBytes(count: Int) -> Data {
        var bytes = Data(count: count)
        _ = bytes.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, count, $0.baseAddress!) }
        return bytes
    }
}
