const fs = require('fs');
const path = require('path');

function walkDir(dir) {
    fs.readdirSync(dir).forEach(f => {
        let dirPath = path.join(dir, f);
        let isDirectory = fs.statSync(dirPath).isDirectory();
        if (isDirectory) {
            walkDir(dirPath);
        } else if (dirPath.endsWith('.ts') || dirPath.endsWith('.tsx') || dirPath.endsWith('.js') || dirPath.endsWith('.jsx')) {
            let content = fs.readFileSync(dirPath, 'utf8');
            if (content.includes('LunaHer') || content.includes('lunaher')) {
                let newContent = content.replace(/LunaHer/g, 'Lunar').replace(/lunaher/g, 'lunar');
                fs.writeFileSync(dirPath, newContent, 'utf8');
                console.log(`Updated ${dirPath}`);
            }
        }
    });
}

walkDir(path.join(__dirname, 'src'));
